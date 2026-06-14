import json
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "test_samples"
    / "glossary_terminology_ru_uk_variants.json"
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

REVIEW_ONLY_OUTCOMES = {
    "TBD",
    "Unknown",
    "needs_review",
    "manual_review_required",
}

REVIEW_REASON_CODES = {
    "morphology_policy_tbd",
    "needs_human_review",
    "policy_manual_review_required",
    "policy_unsupported_language",
    "target_metadata_missing",
}


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise AssertionError("fixture root must be a JSON object")
    return payload


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


class GlossaryTerminologyPolicyFixtureTest(unittest.TestCase):
    def test_fixture_schema_and_guardrails_are_metadata_safe(self):
        fixture = _load_fixture()

        self.assertEqual(
            fixture["schema_version"],
            "glossary-terminology-policy-fixture-v1",
        )
        self.assertEqual(
            fixture["fixture_id"],
            "ru-uk-terminology-variant-policy-metadata-v1",
        )
        self.assertTrue(fixture["owner_approved"])
        self.assertEqual(fixture["scope"], "synthetic_authorized_local_fixture_only")

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

        guardrails = fixture["contract_guardrails"]
        self.assertTrue(guardrails["glossary_core_language_neutral"])
        self.assertTrue(guardrails["ru_uk_represented_as_policy_data"])
        self.assertFalse(guardrails["runtime_prompt_integration_approved"])
        self.assertFalse(guardrails["provider_calls_approved"])
        self.assertFalse(guardrails["cache_behavior_changes_approved"])
        self.assertFalse(guardrails["storage_admin_retention_changes_approved"])
        self.assertFalse(guardrails["release_privacy_legal_support_claims_approved"])
        self.assertFalse(guardrails["full_morphology_correctness_claimed"])

    def test_ru_uk_policies_are_variant_list_data(self):
        fixture = _load_fixture()
        policies = fixture["policies"]
        self.assertEqual(
            {policy["target_language"] for policy in policies},
            {"ru", "uk"},
        )

        for policy in policies:
            with self.subTest(target_language=policy["target_language"]):
                language = policy["target_language"]
                self.assertEqual(
                    policy["policy_id"],
                    f"terminology_policy.{language}.variant_list.fixture_v1",
                )
                self.assertEqual(policy["policy_version"], "v1")
                self.assertEqual(policy["match_mode"], "variant_list")
                self.assertEqual(policy["normalization_mode"], "unicode_nfc_exact")
                self.assertEqual(
                    policy["allowed_variant_strategy"],
                    "explicit_fixture_variants_only",
                )
                self.assertEqual(
                    policy["forbidden_variant_strategy"],
                    "explicit_forbidden_forms_only",
                )
                self.assertEqual(
                    policy["unsupported_fallback"],
                    "manual_review_required",
                )
                self.assertIn("policy_variant_match", policy["reason_codes"])
                self.assertIn(
                    "policy_forbidden_variant_present",
                    policy["reason_codes"],
                )
                self.assertIn("morphology_policy_tbd", policy["reason_codes"])

                approved_case_count = 0
                forbidden_case_count = 0
                for entry in policy["entries"]:
                    entry_id = entry["entry_id"]
                    self.assertTrue(entry_id.startswith(f"{language}-"))
                    self.assertIsInstance(entry["source_canonical"], str)
                    self.assertIsInstance(entry["target_canonical"], str)
                    self.assertGreater(len(entry["approved_variants"]), 0)
                    self.assertGreater(len(entry["forbidden_variants"]), 0)
                    self.assertTrue(
                        set(entry["approved_variants"]).isdisjoint(
                            entry["forbidden_variants"]
                        )
                    )
                    self.assertNotIn(
                        entry["target_canonical"],
                        entry["forbidden_variants"],
                    )
                    for case in entry["expected_cases"]:
                        if case["expected_outcome"] == "approved_variant":
                            approved_case_count += 1
                            self.assertIn(case["form"], entry["approved_variants"])
                            self.assertEqual(
                                case["reason_codes"],
                                ["policy_variant_match"],
                            )
                        elif case["expected_outcome"] == "forbidden_variant":
                            forbidden_case_count += 1
                            self.assertIn(case["form"], entry["forbidden_variants"])
                            self.assertEqual(
                                case["reason_codes"],
                                ["policy_forbidden_variant_present"],
                            )
                        else:
                            self.fail(f"unexpected fixture case outcome: {case}")

                self.assertGreaterEqual(approved_case_count, 3)
                self.assertGreaterEqual(forbidden_case_count, 3)

    def test_missing_and_unsupported_morphology_stays_review_only(self):
        fixture = _load_fixture()
        coverage_gaps = fixture["coverage_gaps"]
        self.assertGreaterEqual(len(coverage_gaps), 5)

        languages_with_gaps = {case["target_language"] for case in coverage_gaps}
        self.assertIn("ru", languages_with_gaps)
        self.assertIn("uk", languages_with_gaps)
        self.assertIn("pl", languages_with_gaps)

        for case in coverage_gaps:
            with self.subTest(case_id=case["case_id"]):
                self.assertIn(case["expected_outcome"], REVIEW_ONLY_OUTCOMES)
                self.assertNotEqual(case["expected_outcome"], "pass")
                self.assertTrue(set(case["reason_codes"]) & REVIEW_REASON_CODES)

        unsupported = next(
            case
            for case in coverage_gaps
            if case["case_id"] == "unsupported-target-language-fallback"
        )
        self.assertEqual(unsupported["policy_id"], None)
        self.assertEqual(unsupported["expected_outcome"], "manual_review_required")
        self.assertIn("policy_unsupported_language", unsupported["reason_codes"])

    def test_fixture_contains_no_runtime_provider_prompt_or_secret_material(self):
        fixture = _load_fixture()

        for value in _walk_values(fixture):
            if isinstance(value, str):
                self.assertNotIn("\n", value)
                for sentinel in FORBIDDEN_VALUE_SENTINELS:
                    self.assertNotIn(sentinel, value)

        self._assert_no_forbidden_fields(fixture)

    def _assert_no_forbidden_fields(self, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized_key = str(key).strip().lower()
                self.assertNotIn(normalized_key, FORBIDDEN_FIELD_NAMES)
                self.assertFalse(normalized_key.startswith("raw_"))
                self._assert_no_forbidden_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                self._assert_no_forbidden_fields(nested)


if __name__ == "__main__":
    unittest.main()
