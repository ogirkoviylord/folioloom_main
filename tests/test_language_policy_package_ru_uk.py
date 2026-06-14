import json
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from translator_service.glossary_compliance import validate_glossary_compliance
from translator_service.glossary_terminology_policy import (
    TerminologyMatchMode,
    TerminologyMatchStatus,
    TerminologyPolicy,
    TerminologyPolicyRegistry,
    match_terminology_target,
    validate_terminology_policy,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "test_samples"
    / "language_policy_packages"
    / "ru_uk_v1.json"
)

CORE_POLICY_MODULES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "translator_service"
    / "glossary_terminology_policy.py",
    Path(__file__).resolve().parents[1]
    / "src"
    / "translator_service"
    / "glossary_compliance.py",
)

FORBIDDEN_FIELD_NAMES = {
    "api_key",
    "authorization",
    "auth_material",
    "password",
    "prompt",
    "prompt_body",
    "provider_request",
    "provider_response",
    "raw_provider_response",
    "raw_source_passage",
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
    "PROMPT BODY MUST NOT SERIALIZE",
    "PROVIDER RESPONSE MUST NOT SERIALIZE",
    "RAW SOURCE PASSAGE MUST NOT SERIALIZE",
    "RAW TRANSLATION MUST NOT SERIALIZE",
    "sk-test-secret-must-not-serialize",
)


def _load_package() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        package = json.load(handle)
    if not isinstance(package, dict):
        raise AssertionError("package fixture root must be a JSON object")
    return package


def _policy_from_descriptor(descriptor: Mapping[str, Any]) -> TerminologyPolicy:
    return TerminologyPolicy(
        policy_id=str(descriptor["policy_id"]),
        policy_version=str(descriptor["policy_version"]),
        target_language=descriptor.get("target_language"),
        language_family=descriptor.get("language_family"),
        match_mode=descriptor["match_mode"],
        normalization_mode=descriptor["normalization_mode"],
        allowed_variant_strategy=descriptor["allowed_variant_strategy"],
        forbidden_variant_strategy=descriptor["forbidden_variant_strategy"],
        unsupported_fallback=descriptor["unsupported_fallback"],
        reason_codes=tuple(descriptor["reason_codes"]),
    )


def _registry(package: Mapping[str, Any]) -> TerminologyPolicyRegistry:
    return TerminologyPolicyRegistry(
        _policy_from_descriptor(policy) for policy in package["policies"]
    )


def _policy_descriptor(
    package: Mapping[str, Any],
    target_language: str,
) -> Mapping[str, Any]:
    for policy in package["policies"]:
        if policy["target_language"] == target_language:
            return policy
    raise AssertionError(f"missing policy for target language {target_language}")


def _entry_descriptor(
    policy: Mapping[str, Any],
    entry_id: str,
) -> Mapping[str, Any]:
    for entry in policy["entries"]:
        if entry["entry_id"] == entry_id:
            return entry
    raise AssertionError(f"missing entry {entry_id}")


def _glossary_entry(entry: Mapping[str, Any]) -> dict[str, object]:
    return {
        "entry_id": entry["entry_id"],
        "source_canonical": entry["source_canonical"],
        "aliases": tuple(entry.get("aliases", ())),
        "target_canonical": entry.get("target_canonical"),
        "target_variants": tuple(entry.get("approved_variants", ())),
        "forbidden_variants": tuple(entry.get("forbidden_variants", ())),
    }


def _source_phrase(entry: Mapping[str, Any]) -> str:
    aliases = entry.get("aliases") or ()
    if aliases:
        return str(aliases[0])
    return str(entry["source_canonical"])


class RuUkLanguagePolicyPackageTest(unittest.TestCase):
    def test_package_descriptor_metadata_and_core_neutrality_are_explicit(self):
        package = _load_package()

        self.assertEqual(package["schema_version"], "language-policy-package-v1")
        self.assertEqual(
            package["package_id"],
            "language_policy.ru_uk.variant_list.v1",
        )
        self.assertRegex(package["package_version"], r"^v[0-9]+$")
        self.assertEqual(package["target_languages"], ["ru", "uk"])
        self.assertEqual(package["language_family"], "east_slavic")
        self.assertEqual(package["match_mode"], "variant_list")
        self.assertEqual(package["normalization_mode"], "nfc")
        self.assertEqual(package["fixture_basis"], "synthetic")
        self.assertEqual(package["evidence_level"], "L1_synthetic_local")
        self.assertEqual(
            package["raw_material_policy"],
            "ordinary_artifacts_metadata_only",
        )
        self.assertEqual(package["full_morphology_engine"], "TBD")
        self.assertEqual(package["quality_evidence"], "Unknown")
        self.assertEqual(package["provider_behavior"], "Unknown")

        thresholds = package["local_thresholds"]
        self.assertTrue(thresholds["descriptor_validation_required"])
        self.assertTrue(thresholds["registry_resolution_required"])
        self.assertGreaterEqual(
            thresholds["min_approved_variant_cases_per_language"],
            2,
        )
        self.assertGreaterEqual(
            thresholds["min_forbidden_variant_cases_per_language"],
            2,
        )
        self.assertTrue(thresholds["default_exact_compatibility_required"])
        self.assertTrue(thresholds["ordinary_payload_metadata_only_required"])

        safety = package["ordinary_artifact_safety"]
        self.assertTrue(safety["metadata_only"])
        self.assertFalse(safety["contains_raw_source_passages"])
        self.assertFalse(safety["contains_translated_passages"])
        self.assertFalse(safety["contains_prompt_bodies"])
        self.assertFalse(safety["contains_provider_requests"])
        self.assertFalse(safety["contains_provider_responses"])
        self.assertFalse(safety["contains_api_keys_or_auth_material"])
        self.assertFalse(safety["release_privacy_legal_support_claim_made"])
        self.assertFalse(safety["runtime_rollout_approved"])
        self.assertFalse(safety["provider_calls_approved"])
        self.assertFalse(safety["cache_reuse_approved"])

        core_neutrality = package["core_neutrality_check"]
        self.assertEqual(
            core_neutrality["registry_boundary"],
            "target_language -> terminology_policy",
        )
        self.assertFalse(core_neutrality["target_language_specific_core_branches"])
        self.assertFalse(core_neutrality["core_modules_changed_by_package"])
        self.assertFalse(core_neutrality["semantic_truth_claim_made"])
        self.assertFalse(core_neutrality["full_morphology_claim_made"])

        for module_path in CORE_POLICY_MODULES:
            module_text = module_path.read_text(encoding="utf-8")
            self.assertNotIn("language_policy.ru_uk.variant_list.v1", module_text)
            self.assertNotIn("language_policy_packages/ru_uk_v1.json", module_text)

    def test_policy_descriptors_validate_and_registry_resolves_language_and_family(
        self,
    ):
        package = _load_package()
        registry = _registry(package)

        for target_language in ("ru", "uk"):
            with self.subTest(target_language=target_language):
                descriptor = _policy_descriptor(package, target_language)
                policy = _policy_from_descriptor(descriptor)
                validation = validate_terminology_policy(policy)

                self.assertTrue(validation.valid, validation.issues)
                self.assertEqual(policy.policy_version, "v1")
                self.assertEqual(policy.match_mode, "variant_list")
                self.assertEqual(policy.normalization_mode, "nfc")
                self.assertEqual(
                    policy.allowed_variant_strategy,
                    "canonical_and_variants",
                )
                self.assertEqual(
                    policy.forbidden_variant_strategy,
                    "configured_forbidden_variants",
                )
                self.assertIn("morphology_policy_tbd", policy.reason_codes)
                self.assertIn("needs_human_review", policy.reason_codes)

                by_language = registry.resolve(target_language.upper())
                self.assertTrue(by_language.supported)
                self.assertEqual(by_language.policy, policy)
                self.assertEqual(by_language.target_language, target_language)

                by_family = registry.resolve(
                    None,
                    language_family=str(descriptor["language_family"]).upper(),
                )
                self.assertTrue(by_family.supported)
                self.assertEqual(by_family.policy, policy)

    def test_approved_variants_and_forbidden_variants_match_through_registry(self):
        package = _load_package()
        registry = _registry(package)

        for descriptor in package["policies"]:
            target_language = descriptor["target_language"]
            resolution = registry.resolve(target_language)
            self.assertIsNotNone(resolution.policy)
            policy = resolution.policy
            approved_case_count = 0
            forbidden_case_count = 0

            for case in descriptor["expected_cases"]:
                entry = _entry_descriptor(descriptor, case["entry_id"])
                result = match_terminology_target(
                    policy,
                    translated_text=f"Controlled local output: {case['form']}.",
                    target_canonical=entry["target_canonical"],
                    target_variants=entry["approved_variants"],
                    forbidden_variants=entry["forbidden_variants"],
                )

                if case["expected_outcome"] == "approved_variant":
                    approved_case_count += 1
                    self.assertEqual(result.status, TerminologyMatchStatus.MATCH)
                    self.assertEqual(result.matched_form_kind, "variant")
                    self.assertIn("policy_variant_match", result.reason_codes)
                    self.assertFalse(result.full_morphology_claim_made)
                elif case["expected_outcome"] == "forbidden_variant":
                    forbidden_case_count += 1
                    self.assertEqual(
                        result.status,
                        TerminologyMatchStatus.FORBIDDEN_VARIANT,
                    )
                    self.assertTrue(result.forbidden_form_match)
                    self.assertIn(
                        "policy_forbidden_variant_present",
                        result.reason_codes,
                    )
                else:
                    self.fail(f"unexpected outcome {case['expected_outcome']}")

            self.assertGreaterEqual(approved_case_count, 2)
            self.assertGreaterEqual(forbidden_case_count, 2)

    def test_compliance_distinguishes_approved_and_forbidden_variants(self):
        package = _load_package()
        registry = _registry(package)
        descriptor = _policy_descriptor(package, "uk")
        entry = _entry_descriptor(descriptor, "uk-glass-market")

        approved = validate_glossary_compliance(
            [_glossary_entry(entry)],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text=f"{_source_phrase(entry)} appears in the fixture.",
            translated_text="На Дзеркальному Торзі чекали до ранку.",
            target_language="uk",
            terminology_policy_registry=registry,
        )
        forbidden = validate_glossary_compliance(
            [_glossary_entry(entry)],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text=f"{_source_phrase(entry)} appears in the fixture.",
            translated_text="Скляний ринок чекали до ранку.",
            target_language="uk",
            terminology_policy_registry=registry,
        )

        self.assertEqual(approved["status"], "pass")
        self.assertEqual(approved["target_form_present_entry_ids"], [entry["entry_id"]])
        self.assertEqual(
            approved["entries"][0]["terminology_match"]["matched_form_kind"],
            "variant",
        )
        self.assertEqual(forbidden["status"], "findings")
        self.assertEqual(forbidden["forbidden_variant_entry_ids"], [entry["entry_id"]])
        self.assertIn("policy_forbidden_variant_present", forbidden["reason_codes"])
        self.assertTrue(approved["metadata_only"])
        self.assertTrue(forbidden["metadata_only"])

    def test_source_absent_and_missing_target_metadata_are_safe_fallbacks(self):
        package = _load_package()
        registry = _registry(package)
        descriptor = _policy_descriptor(package, "ru")
        entry = _entry_descriptor(descriptor, "ru-glass-market")

        source_absent = validate_glossary_compliance(
            [_glossary_entry(entry)],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text="No configured package term is present here.",
            translated_text="Зеркального Торга тут достаточно для проверки.",
            target_language="ru",
            terminology_policy_registry=registry,
        )

        missing_target_case = package["missing_target_metadata_cases"][0]
        missing_target = validate_glossary_compliance(
            [_glossary_entry(missing_target_case)],
            selected_entry_ids=(missing_target_case["entry_id"],),
            included_entry_ids=(missing_target_case["entry_id"],),
            source_text=f"{missing_target_case['source_canonical']} appears here.",
            translated_text="Configured local output.",
            target_language=missing_target_case["target_language"],
            terminology_policy_registry=registry,
        )

        self.assertEqual(source_absent["status"], "skipped")
        self.assertEqual(source_absent["checked_entry_count"], 0)
        self.assertEqual(source_absent["skipped_entry_ids"], [entry["entry_id"]])
        self.assertIn("source_term_absent", source_absent["reason_codes"])
        self.assertEqual(missing_target["status"], "skipped")
        self.assertEqual(
            missing_target["skipped_entry_ids"],
            [missing_target_case["entry_id"]],
        )
        self.assertIn("target_metadata_missing", missing_target["reason_codes"])

    def test_unlisted_morphology_falls_back_without_claiming_morphology_truth(self):
        package = _load_package()
        registry = _registry(package)

        for case in package["unlisted_morphology_cases"]:
            with self.subTest(case_id=case["case_id"]):
                descriptor = _policy_descriptor(package, case["target_language"])
                entry = _entry_descriptor(descriptor, case["entry_id"])
                result = validate_glossary_compliance(
                    [_glossary_entry(entry)],
                    selected_entry_ids=(entry["entry_id"],),
                    included_entry_ids=(entry["entry_id"],),
                    source_text=f"{_source_phrase(entry)} appears in the fixture.",
                    translated_text=(
                        f"Controlled local output: {case['unlisted_form']}."
                    ),
                    target_language=case["target_language"],
                    terminology_policy_registry=registry,
                )

                self.assertIn(case["expected_outcome"], {"TBD", "needs_review"})
                self.assertEqual(result["status"], "findings")
                self.assertEqual(
                    result["target_form_missing_entry_ids"],
                    [entry["entry_id"]],
                )
                self.assertIn(
                    "morphology_policy_tbd",
                    result["uncertainty_reason_codes"],
                )
                self.assertFalse(result["semantic_quality_claim_made"])
                self.assertFalse(
                    result["entries"][0]["terminology_match"][
                        "full_morphology_claim_made"
                    ]
                )
                self.assertTrue(
                    {"morphology_policy_tbd", "needs_human_review"}.issubset(
                        set(case["reason_codes"])
                    )
                )

    def test_default_exact_behavior_still_works_without_registry(self):
        package = _load_package()
        descriptor = _policy_descriptor(package, "ru")
        entry = _entry_descriptor(descriptor, "ru-quiet-knife")

        result = validate_glossary_compliance(
            [_glossary_entry(entry)],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text=f"{_source_phrase(entry)} appears in the fixture.",
            translated_text="Молчальником закрыли безопасный локальный пример.",
            target_language="ru",
            terminology_policy_registry=None,
        )

        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["terminology_policy"]["enabled"])
        self.assertEqual(
            result["policy"],
            "exact_configured_target_forms_only_v1",
        )
        self.assertEqual(
            result["terminology_policy"]["match_mode"],
            TerminologyMatchMode.EXACT.value,
        )
        self.assertEqual(result["target_form_present_entry_ids"], [entry["entry_id"]])

    def test_ordinary_payloads_do_not_leak_prompt_provider_secret_material(self):
        package = _load_package()
        self._assert_no_forbidden_fields(package)

        serialized_fixture = json.dumps(package, ensure_ascii=False, sort_keys=True)
        for sentinel in FORBIDDEN_VALUE_SENTINELS:
            self.assertNotIn(sentinel, serialized_fixture)

        registry = _registry(package)
        descriptor = _policy_descriptor(package, "ru")
        entry = _entry_descriptor(descriptor, "ru-glass-market")
        result = validate_glossary_compliance(
            [_glossary_entry(entry)],
            selected_entry_ids=(entry["entry_id"],),
            included_entry_ids=(entry["entry_id"],),
            source_text=(
                f"{_source_phrase(entry)} appears. "
                "PROMPT BODY MUST NOT SERIALIZE "
                "sk-test-secret-must-not-serialize"
            ),
            translated_text=(
                "Зеркального Торга достаточно. "
                "PROVIDER RESPONSE MUST NOT SERIALIZE "
                "RAW TRANSLATION MUST NOT SERIALIZE"
            ),
            target_language="ru",
            terminology_policy_registry=registry,
        )

        serialized_result = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.assertTrue(result["metadata_only"])
        self.assertFalse(result["raw_payload_included"])
        self._assert_no_forbidden_fields(result)
        for sentinel in FORBIDDEN_VALUE_SENTINELS:
            self.assertNotIn(sentinel, serialized_result)

    def _assert_no_forbidden_fields(self, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized_key = str(key).strip().lower()
                self.assertNotIn(normalized_key, FORBIDDEN_FIELD_NAMES)
                self._assert_no_forbidden_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                self._assert_no_forbidden_fields(nested)


if __name__ == "__main__":
    unittest.main()
