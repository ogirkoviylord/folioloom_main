import json
import unittest

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
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
    PreparedGlossaryPackageConfig,
    validate_prepared_glossary_package,
)
from translator_service.glossary_target_metadata_overlay import (
    GlossaryTargetMetadataOverlayConfig,
    apply_glossary_target_metadata_overlay,
)


class PreparedGlossaryPackageTests(unittest.TestCase):
    def test_valid_package_is_ready_and_overlay_compatible(self):
        result = validate_prepared_glossary_package(
            _prepared_payload(),
            target_language="ru",
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.ready_entry_count, 1)
        self.assertEqual(result.metadata["metadata_only"], True)
        self.assertEqual(result.metadata["raw_payload_included"], False)
        self.assertEqual(result.package.entries[0].source_unit_refs, (7,))
        self.assertEqual(
            result.package.entries[0].source_block_refs,
            ("epub:chapter.xhtml:2",),
        )

        overlay_payload = result.package.to_target_metadata_overlay_payload()
        overlay = apply_glossary_target_metadata_overlay(
            _snapshot(),
            overlay_payload,
            target_language="ru",
            config=GlossaryTargetMetadataOverlayConfig(enabled=True),
        )

        self.assertEqual(overlay.status, "applied")
        self.assertEqual(overlay.snapshot.entries[0].target_canonical, "Дарси")
        self.assertEqual(
            overlay.snapshot.entries[0].target_variants,
            ("Дарси", "мистер Дарси"),
        )

    def test_invalid_schema_version_is_rejected(self):
        payload = _prepared_payload(schema_version="wrong")
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertEqual(result.status, "invalid")
        self.assertIn("prepared_glossary_package_schema_invalid", result.reason_codes)
        self.assertIsNone(result.package)

    def test_target_mismatch_is_rejected(self):
        result = validate_prepared_glossary_package(
            _prepared_payload(target_language="uk"),
            target_language="ru",
        )

        self.assertEqual(result.status, "invalid")
        self.assertIn("prepared_glossary_package_target_mismatch", result.reason_codes)

    def test_wrong_provider_role_is_rejected(self):
        payload = _prepared_payload(provider_role_id="deepseek-pro-other-role")
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "prepared_glossary_package_provider_role_invalid",
            result.reason_codes,
        )

    def test_missing_evidence_is_rejected(self):
        payload = _prepared_payload(entries=[_entry_payload(evidence_refs=[])])
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "prepared_glossary_package_evidence_missing",
            result.reason_codes,
        )

    def test_missing_target_metadata_is_rejected(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    target_canonical=None,
                    target_variants=[],
                )
            ]
        )
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "prepared_glossary_package_target_missing",
            result.reason_codes,
        )

    def test_needs_review_is_structurally_valid_but_not_ready(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    needs_review=True,
                    reason_codes=["low_confidence"],
                )
            ]
        )
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "needs_review")
        self.assertIn(
            "prepared_glossary_package_needs_review",
            result.reason_codes,
        )
        self.assertEqual(result.needs_review_entry_count, 1)
        self.assertIsNotNone(result.package)

    def test_low_value_entries_cannot_make_package_ready(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    source_entry_id="entry:then-he",
                    source_canonical="Then He",
                    aliases=["Then", "He"],
                ),
                _entry_payload(
                    source_entry_id="entry:in-god",
                    source_canonical="In God",
                    aliases=["God"],
                ),
            ]
        )

        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "needs_review")
        self.assertIn(
            "prepared_glossary_package_quality_no_ready_entries",
            result.reason_codes,
        )
        self.assertIsNotNone(result.package)
        self.assertEqual(result.package.entries, ())
        self.assertEqual(result.metadata["quality"]["input_candidate_count"], 2)
        self.assertEqual(result.metadata["quality"]["dropped_candidate_count"], 2)
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("Then He", metadata_text)
        self.assertNotIn("In God", metadata_text)

    def test_pg17460_low_value_entries_cannot_make_package_ready(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    source_entry_id="entry:boy-and",
                    source_canonical="BOY AND",
                    aliases=["BOY AND"],
                ),
                _entry_payload(
                    source_entry_id="entry:of-any-kind",
                    source_canonical="OF ANY KIND",
                    aliases=["OF ANY KIND"],
                ),
                _entry_payload(
                    source_entry_id="entry:labour-was",
                    source_canonical="Labour Was",
                    aliases=["Labour Was"],
                ),
                _entry_payload(
                    source_entry_id="entry:good-god",
                    source_canonical="Good God",
                    aliases=["Good God"],
                ),
            ]
        )

        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "needs_review")
        self.assertIn(
            "prepared_glossary_package_quality_no_ready_entries",
            result.reason_codes,
        )
        self.assertIsNotNone(result.package)
        self.assertEqual(result.package.entries, ())
        self.assertEqual(result.metadata["quality"]["input_candidate_count"], 4)
        self.assertEqual(result.metadata["quality"]["dropped_candidate_count"], 4)
        self.assertIn(
            "candidate_quality_function_word_phrase",
            result.metadata["quality"]["reason_codes"],
        )
        self.assertIn(
            "candidate_quality_common_phrase",
            result.metadata["quality"]["reason_codes"],
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        for raw_source in ("BOY AND", "OF ANY KIND", "Labour Was", "Good God"):
            self.assertNotIn(raw_source, metadata_text)

    def test_mixed_quality_package_keeps_valid_entries_metadata_only(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    source_entry_id="entry:then-he",
                    source_canonical="Then He",
                    aliases=["Then", "He"],
                ),
                _entry_payload(
                    source_entry_id="entry:darcy",
                    source_canonical="Mr Darcy",
                    aliases=["Darcy", "He"],
                ),
            ]
        )

        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertTrue(result.ready)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.ready_entry_count, 1)
        self.assertEqual(result.metadata["quality"]["input_candidate_count"], 2)
        self.assertEqual(result.metadata["quality"]["dropped_candidate_count"], 1)
        self.assertEqual(result.metadata["quality"]["alias_omitted_count"], 3)
        self.assertEqual(len(result.package.entries), 1)
        self.assertEqual(result.package.entries[0].source_canonical, "Mr Darcy")
        self.assertEqual(result.package.entries[0].aliases, ("Darcy",))
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        self.assertNotIn("Then He", metadata_text)
        self.assertNotIn("Mr Darcy", metadata_text)

    def test_possessive_corrupted_and_vocative_entries_cannot_make_package_ready(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    source_entry_id="entry:darcy-possessive",
                    source_canonical="Mr Darcy's",
                    aliases=["Mr Darcy's"],
                ),
                _entry_payload(
                    source_entry_id="entry:john-corrupted",
                    source_canonical="John s",
                    aliases=["John s"],
                ),
                _entry_payload(
                    source_entry_id="entry:oh-john",
                    source_canonical="Oh John",
                    aliases=["Oh John"],
                ),
            ]
        )

        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertFalse(result.ready)
        self.assertEqual(result.status, "needs_review")
        self.assertIn(
            "prepared_glossary_package_quality_no_ready_entries",
            result.reason_codes,
        )
        assert result.package is not None
        self.assertEqual(result.package.entries, ())
        self.assertEqual(result.metadata["quality"]["dropped_candidate_count"], 3)
        self.assertIn(
            "candidate_quality_possessive_source",
            result.metadata["quality"]["reason_codes"],
        )
        self.assertIn(
            "candidate_quality_corrupted_possessive_source",
            result.metadata["quality"]["reason_codes"],
        )
        self.assertIn(
            "candidate_quality_vocative_phrase",
            result.metadata["quality"]["reason_codes"],
        )
        metadata_text = json.dumps(result.metadata, ensure_ascii=False)
        for unsafe in ("Mr Darcy's", "John s", "Oh John"):
            self.assertNotIn(unsafe, metadata_text)

    def test_broad_first_name_alias_is_pruned_from_ready_package(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    source_entry_id="entry:alice-winterbourne",
                    source_canonical="Alice Winterbourne",
                    aliases=["Alice", "Winterbourne", "Lizzy"],
                ),
                _entry_payload(
                    source_entry_id="entry:mr-darcy",
                    source_canonical="Mr Darcy",
                    aliases=["Darcy"],
                ),
            ]
        )

        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertTrue(result.ready)
        self.assertEqual(result.ready_entry_count, 2)
        assert result.package is not None
        self.assertEqual(
            result.package.entries[0].aliases,
            ("Winterbourne", "Lizzy"),
        )
        self.assertEqual(result.package.entries[1].aliases, ("Darcy",))
        self.assertEqual(result.metadata["quality"]["alias_omitted_count"], 1)
        self.assertIn(
            "candidate_quality_broad_alias_pruned",
            result.metadata["quality"]["reason_codes"],
        )

    def test_bool_confidence_is_rejected(self):
        payload = _prepared_payload(entries=[_entry_payload(confidence=True)])
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "prepared_glossary_package_confidence_invalid",
            result.reason_codes,
        )

    def test_raw_and_secret_material_are_rejected_and_not_serialized(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    raw_source="RAW SOURCE MUST NOT LEAK",
                    prompt_body="PROMPT MUST NOT LEAK",
                    target_variants=["sk-testsecret000000000000"],
                    provider_response={"body": "RAW RESPONSE MUST NOT LEAK"},
                )
            ],
            authorization="Bearer not-a-real-token",
            provider_request={"messages": ["RAW PROMPT"]},
        )
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "prepared_glossary_package_raw_field_present",
            result.reason_codes,
        )
        self.assertIn(
            "prepared_glossary_package_secret_field_present",
            result.reason_codes,
        )
        self.assertIn(
            "prepared_glossary_package_secret_material_present",
            result.reason_codes,
        )
        serialized = json.dumps(result.metadata, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("RAW SOURCE", serialized)
        self.assertNotIn("PROMPT MUST", serialized)
        self.assertNotIn("RAW RESPONSE", serialized)
        self.assertNotIn("Bearer", serialized)
        self.assertNotIn("sk-testsecret", serialized)

    def test_entry_limit_fails_metadata_only(self):
        payload = _prepared_payload(entries=[_entry_payload(), _entry_payload()])
        result = validate_prepared_glossary_package(
            payload,
            target_language="ru",
            config=PreparedGlossaryPackageConfig(max_entries=1),
        )

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "prepared_glossary_package_entry_limit_exceeded",
            result.reason_codes,
        )
        self.assertEqual(result.metadata["entry_count"], 0)

    def test_unsupported_field_is_rejected(self):
        payload = _prepared_payload(unexpected_field="nope")
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "prepared_glossary_package_unsupported_field",
            result.reason_codes,
        )

    def test_invalid_source_refs_are_rejected(self):
        payload = _prepared_payload(
            entries=[
                _entry_payload(
                    source_unit_refs=["7"],
                    source_block_refs=[{"raw": "nope"}],
                )
            ]
        )
        result = validate_prepared_glossary_package(payload, target_language="ru")

        self.assertEqual(result.status, "invalid")
        self.assertIn(
            "prepared_glossary_package_source_unit_refs_invalid",
            result.reason_codes,
        )
        self.assertIn(
            "prepared_glossary_package_source_block_refs_invalid",
            result.reason_codes,
        )


def _snapshot() -> GlossarySnapshot:
    return GlossarySnapshot(
        snapshot_id="snapshot:test",
        source_language="en",
        target_language="ru",
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


def _prepared_payload(
    *,
    schema_version: str = GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
    target_language: str = "ru",
    entries: list[dict[str, object]] | None = None,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "package_id": "prepared:darcy:ru",
        "source_language": "en",
        "target_language": target_language,
        "glossary_mode": "with_glossary",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": "deepseek-v4-pro",
        "provider_run_id": "provider-run:fake",
        "diagnostics_ref": "outputs/glossary-battle-test/fake",
        "source_document_fingerprint": "doc:fake",
        "candidate_selector_signature": "selector:fake",
        "glossary_snapshot_signature": "snapshot:fake",
        "language_policy_package_id": "terminology_policy.ru_uk.ru.variant_list.v1",
        "language_policy_package_version": "v1",
        "owner_approved": True,
        "entries": entries if entries is not None else [_entry_payload()],
    }
    payload.update(extra)
    return payload


def _entry_payload(
    *,
    target_canonical: str | None = "Дарси",
    target_variants: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    needs_review: bool = False,
    reason_codes: list[str] | None = None,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_entry_id": "entry:darcy",
        "source_canonical": "Darcy",
        "aliases": ["Mr. Darcy"],
        "evidence_refs": (
            evidence_refs if evidence_refs is not None else ["evidence:darcy"]
        ),
        "source_unit_refs": [7],
        "source_block_refs": ["epub:chapter.xhtml:2"],
        "target_canonical": target_canonical,
        "target_variants": (
            target_variants
            if target_variants is not None
            else ["Дарси", "мистер Дарси"]
        ),
        "forbidden_variants": ["Дорси"],
        "strategy": "transcribe",
        "confidence": 0.91,
        "needs_review": needs_review,
        "reason_codes": reason_codes or [],
        "terminology_policy_metadata": {
            "policy_id": "ru-variant-list",
            "policy_version": "v1",
            "match_mode": "variant_list",
        },
    }
    payload.update(extra)
    return payload


if __name__ == "__main__":
    unittest.main()
