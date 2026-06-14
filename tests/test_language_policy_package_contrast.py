import json
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from translator_service.glossary_compliance import validate_glossary_compliance
from translator_service.glossary_terminology_policy import (
    TerminologyMatchStatus,
    TerminologyPolicy,
    TerminologyPolicyReasonCode,
    TerminologyPolicyRegistry,
    match_terminology_target,
    terminology_match_payload,
    terminology_policy_resolution_payload,
    validate_terminology_policy,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "test_samples"
    / "language_policy_packages"
    / "contrast_casefold_v1.json"
)

FORBIDDEN_FIELD_NAMES = {
    "api_key",
    "authorization",
    "auth_material",
    "owner_only_diagnostics",
    "password",
    "prompt",
    "prompt_body",
    "provider_request",
    "provider_response",
    "raw_provider_response",
    "raw_source",
    "raw_target",
    "raw_translation",
    "secret",
    "source_text",
    "system_prompt",
    "translated_passage",
    "translated_text",
    "user_prompt",
}

FORBIDDEN_VALUE_SENTINELS = (
    "BEGIN_UNTRUSTED_DOCUMENT_CONTENT",
    "<glossary_context",
    "<translation_batch",
    "Authorization:",
    "Bearer ",
    "RAW PROVIDER",
    "RAW SOURCE MUST NOT SERIALIZE",
    "RAW TARGET MUST NOT SERIALIZE",
    "RAW TRANSLATION MUST NOT SERIALIZE",
    "sk-",
)

ALLOWED_METADATA_RAW_KEYS = {
    "raw_material_policy",
    "raw_payload_allowed",
}


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise AssertionError("fixture root must be a JSON object")
    return payload


def _policy_from_fixture(fixture: Mapping[str, Any]) -> TerminologyPolicy:
    policy = fixture["policy"]
    return TerminologyPolicy(
        policy_id=policy["policy_id"],
        policy_version=policy["policy_version"],
        target_language=policy["target_language"],
        language_family=policy["language_family"],
        match_mode=policy["match_mode"],
        normalization_mode=policy["normalization_mode"],
        allowed_variant_strategy=policy["allowed_variant_strategy"],
        forbidden_variant_strategy=policy["forbidden_variant_strategy"],
        unsupported_fallback=policy["unsupported_fallback"],
        reason_codes=tuple(policy["reason_codes"]),
    )


def _first_entry(fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    entries = fixture["entries"]
    if not isinstance(entries, list) or not entries:
        raise AssertionError("fixture must contain at least one entry")
    entry = entries[0]
    if not isinstance(entry, Mapping):
        raise AssertionError("fixture entry must be an object")
    return entry


def _case(entry: Mapping[str, Any], expected_outcome: str) -> Mapping[str, Any]:
    for item in entry["expected_cases"]:
        if item["expected_outcome"] == expected_outcome:
            return item
    raise AssertionError(f"missing expected fixture case: {expected_outcome}")


def _entry_payload(entry: Mapping[str, Any]) -> dict[str, object]:
    return {
        "entry_id": entry["entry_id"],
        "source_canonical": entry["source_canonical"],
        "aliases": tuple(entry["aliases"]),
        "target_canonical": entry["target_canonical"],
        "target_variants": tuple(entry["target_variants"]),
        "forbidden_variants": tuple(entry["forbidden_variants"]),
    }


def _walk_values(value: Any) -> Sequence[Any]:
    seen: list[Any] = [value]
    if isinstance(value, Mapping):
        for key, nested in value.items():
            seen.append(key)
            seen.extend(_walk_values(nested))
    elif isinstance(value, list):
        for nested in value:
            seen.extend(_walk_values(nested))
    return seen


class LanguagePolicyPackageContrastTest(unittest.TestCase):
    def test_descriptor_declares_conservative_de_casefold_package(self):
        fixture = _load_fixture()

        self.assertEqual(fixture["schema_version"], "language-policy-package-v1")
        self.assertEqual(
            fixture["package_id"],
            "language_policy.de.casefold.contrast_v1",
        )
        self.assertEqual(fixture["package_version"], "v1")
        self.assertEqual(fixture["readiness_label"], "package_ready_local")
        self.assertEqual(fixture["target_language"], "de")
        self.assertNotIn(fixture["target_language"], {"ru", "uk"})
        self.assertEqual(fixture["match_mode"], "casefold")
        self.assertEqual(fixture["normalization_mode"], "nfc_casefold")
        self.assertEqual(fixture["fixture_basis"], "synthetic")
        self.assertEqual(fixture["evidence_level"], "L1_synthetic_local")
        self.assertEqual(
            fixture["raw_material_policy"],
            "ordinary_artifacts_metadata_only",
        )

        thresholds = fixture["local_thresholds"]
        self.assertTrue(thresholds["descriptor_validation_required"])
        self.assertTrue(thresholds["terminology_policy_validation_required"])
        self.assertGreaterEqual(thresholds["positive_match_cases_min"], 1)
        self.assertGreaterEqual(thresholds["safe_fallback_cases_min"], 1)
        self.assertGreaterEqual(thresholds["forbidden_variant_findings_min"], 1)
        self.assertFalse(thresholds["raw_payload_allowed"])
        self.assertFalse(thresholds["semantic_quality_claim_allowed"])
        self.assertFalse(thresholds["full_morphology_claim_allowed"])
        self.assertFalse(thresholds["core_language_branches_allowed"])

        core = fixture["core_neutrality_check"]
        self.assertEqual(core["non_ru_uk_target_language"], "de")
        self.assertTrue(core["selected_through_registry"])
        self.assertTrue(core["target_language_specific_data_lives_in_package"])
        self.assertTrue(core["glossary_core_language_neutral"])
        self.assertTrue(core["no_target_language_branch_in_core_required"])
        self.assertTrue(core["compliance_structural_validation_separate"])
        self.assertTrue(core["prompt_metadata_compact_only"])
        self.assertFalse(core["cache_reuse_approved"])
        self.assertFalse(core["runtime_rollout_approved"])
        self.assertFalse(core["provider_calls_approved"])
        self.assertFalse(core["release_privacy_legal_support_claims_approved"])

        safety = fixture["metadata_safety"]
        self.assertTrue(safety["metadata_only"])
        self.assertTrue(safety["synthetic_or_authorized"])
        self.assertFalse(safety["contains_raw_source_passages"])
        self.assertFalse(safety["contains_translated_passages"])
        self.assertFalse(safety["contains_prompt_bodies"])
        self.assertFalse(safety["contains_provider_responses"])
        self.assertFalse(safety["contains_owner_only_diagnostics"])
        self.assertFalse(safety["contains_api_keys_or_auth_material"])
        self.assertFalse(safety["semantic_quality_claim_made"])
        self.assertFalse(safety["full_morphology_correctness_claimed"])

    def test_policy_validates_and_resolves_through_registry_boundary(self):
        fixture = _load_fixture()
        policy = _policy_from_fixture(fixture)

        validation = validate_terminology_policy(policy)
        self.assertTrue(validation.valid, validation.issues)

        registry = TerminologyPolicyRegistry((policy,))
        resolution = registry.resolve("DE")
        payload = terminology_policy_resolution_payload(resolution)

        self.assertTrue(resolution.supported)
        self.assertEqual(resolution.policy, policy)
        self.assertEqual(payload["target_language"], "de")
        self.assertEqual(
            payload["policy_id"],
            "terminology_policy.de.casefold.contrast_v1",
        )
        self.assertEqual(payload["policy_version"], "v1")
        self.assertTrue(payload["metadata_only"])
        self.assertFalse(payload["raw_payload_included"])
        self.assertFalse(payload["semantic_quality_claim_made"])
        self.assertFalse(payload["full_morphology_claim_made"])

        unsupported = registry.resolve("ru")
        unsupported_payload = terminology_policy_resolution_payload(unsupported)
        self.assertFalse(unsupported.supported)
        self.assertIsNone(unsupported.policy)
        self.assertEqual(unsupported_payload["fallback"], "manual_review_required")
        self.assertIn(
            "policy_unsupported_language",
            unsupported_payload["reason_codes"],
        )
        self.assertIn("needs_human_review", unsupported_payload["reason_codes"])

    def test_casefold_match_and_forbidden_form_use_existing_matcher(self):
        fixture = _load_fixture()
        policy = _policy_from_fixture(fixture)
        entry = _first_entry(fixture)
        casefold_case = _case(entry, "casefold_match")
        forbidden_case = _case(entry, "forbidden_variant")

        match = match_terminology_target(
            policy,
            translated_text=f"Local synthetic output: {casefold_case['form']}.",
            target_canonical=entry["target_canonical"],
            forbidden_variants=entry["forbidden_variants"],
        )
        forbidden = match_terminology_target(
            policy,
            translated_text=f"Local synthetic output: {forbidden_case['form']}.",
            target_canonical=entry["target_canonical"],
            forbidden_variants=entry["forbidden_variants"],
        )
        match_payload = terminology_match_payload(match)
        forbidden_payload = terminology_match_payload(forbidden)

        self.assertEqual(match.status, TerminologyMatchStatus.MATCH)
        self.assertTrue(match.checked)
        self.assertTrue(match.local_form_match)
        self.assertFalse(match.forbidden_form_match)
        self.assertEqual(match.matched_form_kind, "canonical")
        self.assertIn(
            TerminologyPolicyReasonCode.POLICY_CASEFOLD_MATCH,
            match.reason_codes,
        )
        self.assertEqual(match_payload["match_mode"], "casefold")
        self.assertFalse(match_payload["full_morphology_claim_made"])

        self.assertEqual(forbidden.status, TerminologyMatchStatus.FORBIDDEN_VARIANT)
        self.assertTrue(forbidden.checked)
        self.assertFalse(forbidden.local_form_match)
        self.assertTrue(forbidden.forbidden_form_match)
        self.assertEqual(forbidden.matched_form_kind, "forbidden_variant")
        self.assertIn(
            "policy_forbidden_variant_present",
            forbidden_payload["reason_codes"],
        )
        self.assertFalse(forbidden_payload["semantic_quality_claim_made"])

    def test_compliance_preserves_default_exact_and_enables_casefold_policy(self):
        fixture = _load_fixture()
        policy = _policy_from_fixture(fixture)
        registry = TerminologyPolicyRegistry((policy,))
        entry = _first_entry(fixture)
        entry_payload = _entry_payload(entry)
        casefold_case = _case(entry, "casefold_match")

        default_exact = validate_glossary_compliance(
            [entry_payload],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text="The Mirror Street marker is present.",
            translated_text=f"{entry['target_canonical']} marker.",
        )
        default_exact_miss = validate_glossary_compliance(
            [entry_payload],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text="The Mirror Street marker is present.",
            translated_text=f"{casefold_case['form']} marker.",
        )
        casefold_hit = validate_glossary_compliance(
            [entry_payload],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text="The Mirror Street marker is present.",
            translated_text=f"{casefold_case['form']} marker.",
            target_language="de",
            terminology_policy_registry=registry,
        )

        self.assertEqual(default_exact["status"], "pass")
        self.assertFalse(default_exact["terminology_policy"]["enabled"])
        self.assertEqual(
            default_exact["policy"],
            "exact_configured_target_forms_only_v1",
        )
        self.assertEqual(default_exact_miss["status"], "findings")
        self.assertEqual(default_exact_miss["target_form_missing_count"], 1)
        self.assertIn("target_form_missing", default_exact_miss["reason_codes"])

        self.assertEqual(casefold_hit["status"], "pass")
        self.assertEqual(
            casefold_hit["policy"],
            "terminology_policy_registry_adapter_v1",
        )
        self.assertTrue(casefold_hit["terminology_policy"]["enabled"])
        self.assertEqual(
            casefold_hit["terminology_policy"]["policy_id"],
            "terminology_policy.de.casefold.contrast_v1",
        )
        self.assertEqual(casefold_hit["terminology_policy"]["match_mode"], "casefold")
        self.assertEqual(casefold_hit["target_form_present_count"], 1)
        self.assertEqual(
            casefold_hit["entries"][0]["terminology_match"]["status"],
            "match",
        )
        self.assertIn(
            "policy_casefold_match",
            casefold_hit["entries"][0]["reason_codes"],
        )

    def test_compliance_records_forbidden_unsupported_and_missing_metadata(self):
        fixture = _load_fixture()
        policy = _policy_from_fixture(fixture)
        registry = TerminologyPolicyRegistry((policy,))
        entry = _first_entry(fixture)
        entry_payload = _entry_payload(entry)
        forbidden_case = _case(entry, "forbidden_variant")

        forbidden = validate_glossary_compliance(
            [entry_payload],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text="The Mirror Street marker is present.",
            translated_text=f"{forbidden_case['form']} marker.",
            target_language="de",
            terminology_policy_registry=registry,
        )
        unsupported = validate_glossary_compliance(
            [entry_payload],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text="The Mirror Street marker is present.",
            translated_text=f"{entry['target_canonical']} marker.",
            target_language="nl",
            terminology_policy_registry=registry,
        )
        missing_target = validate_glossary_compliance(
            [
                {
                    "entry_id": "de-missing-target",
                    "source_canonical": "Missing Target",
                    "target_canonical": None,
                }
            ],
            selected_entry_ids=("de-missing-target",),
            included_entry_ids=("de-missing-target",),
            source_text="Missing Target marker is present.",
            translated_text="Local synthetic output.",
            target_language="de",
            terminology_policy_registry=registry,
        )

        self.assertEqual(forbidden["status"], "findings")
        self.assertEqual(forbidden["forbidden_variant_count"], 1)
        self.assertEqual(forbidden["forbidden_variant_entry_ids"], [entry["entry_id"]])
        self.assertIn("policy_forbidden_variant_present", forbidden["reason_codes"])
        self.assertEqual(
            forbidden["entries"][0]["terminology_match"]["status"],
            "forbidden_variant",
        )

        self.assertEqual(unsupported["status"], "findings")
        self.assertEqual(unsupported["checked_entry_count"], 0)
        self.assertEqual(unsupported["needs_review_entry_count"], 1)
        self.assertEqual(unsupported["terminology_policy"]["supported"], False)
        self.assertIn("policy_unsupported_language", unsupported["reason_codes"])
        self.assertIn("needs_human_review", unsupported["reason_codes"])
        self.assertEqual(
            unsupported["entries"][0]["terminology_match"]["status"],
            "needs_review",
        )

        self.assertEqual(missing_target["status"], "skipped")
        self.assertEqual(missing_target["skipped_entry_count"], 1)
        self.assertIn("target_metadata_missing", missing_target["reason_codes"])

    def test_fixture_contains_no_prompt_provider_secret_or_raw_payload_fields(self):
        fixture = _load_fixture()

        for value in _walk_values(fixture):
            if isinstance(value, str):
                self.assertNotIn("\n", value)
                for sentinel in FORBIDDEN_VALUE_SENTINELS:
                    self.assertNotIn(sentinel, value)

        self._assert_no_forbidden_fields(fixture)

    def test_ordinary_compliance_payload_redacts_raw_inputs_and_secrets(self):
        fixture = _load_fixture()
        policy = _policy_from_fixture(fixture)
        registry = TerminologyPolicyRegistry((policy,))
        raw_source = "RAW SOURCE MUST NOT SERIALIZE"
        raw_target = "RAW TARGET MUST NOT SERIALIZE"
        raw_translation = "RAW TRANSLATION MUST NOT SERIALIZE"

        result = validate_glossary_compliance(
            [
                {
                    "entry_id": "de-redaction",
                    "source_canonical": raw_source,
                    "target_canonical": raw_target,
                }
            ],
            selected_entry_ids=("de-redaction",),
            included_entry_ids=("de-redaction",),
            source_text=f"{raw_source} appears in synthetic local input.",
            translated_text=f"{raw_translation} contains {raw_target}.",
            target_language="de",
            terminology_policy_registry=registry,
        )
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["metadata_only"])
        self.assertFalse(result["raw_payload_included"])
        self.assertFalse(result["semantic_quality_claim_made"])
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn(raw_target, serialized)
        self.assertNotIn(raw_translation, serialized)
        self.assertNotIn("prompt_body", serialized)
        self.assertNotIn("provider_response", serialized)
        self.assertNotIn("sk-", serialized)

    def _assert_no_forbidden_fields(self, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized_key = str(key).strip().lower()
                self.assertNotIn(normalized_key, FORBIDDEN_FIELD_NAMES)
                if normalized_key not in ALLOWED_METADATA_RAW_KEYS:
                    self.assertFalse(normalized_key.startswith("raw_"))
                self._assert_no_forbidden_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                self._assert_no_forbidden_fields(nested)


if __name__ == "__main__":
    unittest.main()
