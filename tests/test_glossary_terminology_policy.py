import json
import unittest

from translator_service.glossary_terminology_policy import (
    DEFAULT_TERMINOLOGY_POLICY_REASON_CODES,
    EMPTY_TERMINOLOGY_POLICY_REGISTRY,
    AllowedVariantStrategy,
    ForbiddenVariantStrategy,
    TerminologyMatchMode,
    TerminologyMatchStatus,
    TerminologyNormalizationMode,
    TerminologyPolicy,
    TerminologyPolicyReasonCode,
    TerminologyPolicyRegistry,
    TerminologyPolicyValidationCode,
    UnsupportedTerminologyFallback,
    match_terminology_target,
    terminology_match_payload,
    terminology_policy_resolution_payload,
    validate_terminology_policy,
)


class GlossaryTerminologyPolicyTest(unittest.TestCase):
    def test_valid_policy_declares_required_contract_fields(self):
        policy = _policy(
            "terminology_policy.generic.exact",
            target_language="es",
            match_mode=TerminologyMatchMode.EXACT,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_ONLY,
        )

        result = validate_terminology_policy(policy)

        self.assertTrue(result.valid, result.issues)
        self.assertEqual(policy.policy_version, "v1")
        self.assertEqual(policy.normalization_mode, TerminologyNormalizationMode.NFC)
        self.assertIn(
            TerminologyPolicyReasonCode.POLICY_TARGET_FORM_MISSING,
            policy.reason_codes,
        )

    def test_invalid_policy_rejects_bad_identifiers_modes_and_reason_codes(self):
        policy = TerminologyPolicy(
            policy_id="Terminology Policy With Spaces",
            policy_version="",
            target_language="English",
            language_family="bad family",
            match_mode="semantic_truth_engine",
            normalization_mode="raw",
            allowed_variant_strategy="invent_variants",
            forbidden_variant_strategy="trust_provider",
            unsupported_fallback="pass",
            reason_codes=("policy_exact_match", "policy_exact_match", "raw_text"),
            schema_version="old-schema",
        )

        result = validate_terminology_policy(policy)
        codes = _codes(result)

        self.assertFalse(result.valid)
        self.assertIn(TerminologyPolicyValidationCode.INVALID_SCHEMA_VERSION, codes)
        self.assertIn(TerminologyPolicyValidationCode.INVALID_POLICY_ID, codes)
        self.assertIn(TerminologyPolicyValidationCode.INVALID_POLICY_VERSION, codes)
        self.assertIn(TerminologyPolicyValidationCode.INVALID_LANGUAGE_TAG, codes)
        self.assertIn(TerminologyPolicyValidationCode.INVALID_LANGUAGE_FAMILY, codes)
        self.assertIn(TerminologyPolicyValidationCode.INVALID_ENUM, codes)
        self.assertIn(TerminologyPolicyValidationCode.INVALID_REASON_CODE, codes)
        self.assertIn(TerminologyPolicyValidationCode.DUPLICATE_REASON_CODE, codes)

    def test_registry_resolves_language_and_family_without_runtime_defaults(self):
        language_policy = _policy(
            "terminology_policy.generic.casefold",
            target_language="es",
            match_mode=TerminologyMatchMode.CASEFOLD,
            normalization_mode=TerminologyNormalizationMode.NFC_CASEFOLD,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_ONLY,
        )
        family_policy = _policy(
            "terminology_policy.generic.latin_variant_list",
            target_language=None,
            language_family="latin-script",
            match_mode=TerminologyMatchMode.VARIANT_LIST,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_AND_VARIANTS,
        )
        registry = TerminologyPolicyRegistry((language_policy, family_policy))

        language_resolution = registry.resolve("ES")
        family_resolution = registry.resolve("it", language_family="latin-script")
        empty_resolution = EMPTY_TERMINOLOGY_POLICY_REGISTRY.resolve("es")

        self.assertTrue(language_resolution.supported)
        self.assertEqual(language_resolution.policy, language_policy)
        self.assertTrue(family_resolution.supported)
        self.assertEqual(family_resolution.policy, family_policy)
        self.assertFalse(empty_resolution.supported)
        self.assertEqual(
            empty_resolution.fallback,
            UnsupportedTerminologyFallback.MANUAL_REVIEW_REQUIRED,
        )

    def test_unsupported_language_fallback_is_metadata_only_not_pass(self):
        registry = TerminologyPolicyRegistry(())

        resolution = registry.resolve("de")
        payload = terminology_policy_resolution_payload(resolution)

        self.assertFalse(resolution.supported)
        self.assertIsNone(resolution.policy)
        self.assertEqual(payload["fallback"], "manual_review_required")
        self.assertIn("policy_unsupported_language", payload["reason_codes"])
        self.assertIn("needs_human_review", payload["reason_codes"])
        self.assertTrue(payload["metadata_only"])
        self.assertFalse(payload["raw_payload_included"])
        self.assertFalse(payload["semantic_quality_claim_made"])
        self.assertFalse(payload["full_morphology_claim_made"])

    def test_exact_matching_uses_configured_canonical_and_variants(self):
        policy = _policy(
            "terminology_policy.generic.exact",
            target_language="es",
            match_mode=TerminologyMatchMode.EXACT,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_AND_VARIANTS,
        )
        hit = match_terminology_target(
            policy,
            translated_text="La Casa Norte aparece aqui.",
            target_canonical="Casa Norte",
            target_variants=("Casa Septentrional",),
        )
        variant_only = match_terminology_target(
            policy,
            translated_text="La Casa Septentrional aparece aqui.",
            target_canonical="Casa Norte",
            target_variants=("Casa Septentrional",),
        )
        canonical_only_policy = _policy(
            "terminology_policy.generic.exact_canonical",
            target_language="es",
            match_mode=TerminologyMatchMode.EXACT,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_ONLY,
        )
        canonical_only_variant = match_terminology_target(
            canonical_only_policy,
            translated_text="La Casa Septentrional aparece aqui.",
            target_canonical="Casa Norte",
            target_variants=("Casa Septentrional",),
        )
        substring = match_terminology_target(
            policy,
            translated_text="Casa Norteno is a different token.",
            target_canonical="Casa Norte",
        )

        self.assertEqual(hit.status, TerminologyMatchStatus.MATCH)
        self.assertTrue(hit.local_form_match)
        self.assertEqual(hit.matched_form_kind, "canonical")
        self.assertIn(TerminologyPolicyReasonCode.POLICY_EXACT_MATCH, hit.reason_codes)
        self.assertEqual(variant_only.status, TerminologyMatchStatus.MATCH)
        self.assertEqual(variant_only.matched_form_kind, "variant")
        self.assertIn(
            TerminologyPolicyReasonCode.POLICY_VARIANT_MATCH,
            variant_only.reason_codes,
        )
        self.assertEqual(canonical_only_variant.status, TerminologyMatchStatus.NO_MATCH)
        self.assertEqual(substring.status, TerminologyMatchStatus.NO_MATCH)

    def test_casefold_matching_is_unicode_casefold_only(self):
        policy = _policy(
            "terminology_policy.generic.casefold",
            target_language="de",
            match_mode=TerminologyMatchMode.CASEFOLD,
            normalization_mode=TerminologyNormalizationMode.NFC_CASEFOLD,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_ONLY,
        )

        result = match_terminology_target(
            policy,
            translated_text="Die STRASSE war leer.",
            target_canonical="Straße",
        )

        self.assertEqual(result.status, TerminologyMatchStatus.MATCH)
        self.assertIn(
            TerminologyPolicyReasonCode.POLICY_CASEFOLD_MATCH,
            result.reason_codes,
        )
        self.assertFalse(result.full_morphology_claim_made)

    def test_variant_list_matching_allows_variants_and_flags_forbidden_forms(self):
        policy = _policy(
            "terminology_policy.generic.variant_list",
            target_language="fr",
            match_mode=TerminologyMatchMode.VARIANT_LIST,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_AND_VARIANTS,
            forbidden_variant_strategy=(
                ForbiddenVariantStrategy.CONFIGURED_FORBIDDEN_VARIANTS
            ),
        )
        variant_hit = match_terminology_target(
            policy,
            translated_text="La Porte Boréale est ouverte.",
            target_canonical="Porte du Nord",
            target_variants=("Porte Boréale",),
            forbidden_variants=("Porte Nord",),
        )
        forbidden_hit = match_terminology_target(
            policy,
            translated_text="La Porte Nord est ouverte.",
            target_canonical="Porte du Nord",
            target_variants=("Porte Boréale",),
            forbidden_variants=("Porte Nord",),
        )

        self.assertEqual(variant_hit.status, TerminologyMatchStatus.MATCH)
        self.assertEqual(variant_hit.matched_form_kind, "variant")
        self.assertIn(
            TerminologyPolicyReasonCode.POLICY_VARIANT_MATCH,
            variant_hit.reason_codes,
        )
        self.assertEqual(
            forbidden_hit.status,
            TerminologyMatchStatus.FORBIDDEN_VARIANT,
        )
        self.assertTrue(forbidden_hit.checked)
        self.assertTrue(forbidden_hit.forbidden_form_match)
        self.assertFalse(forbidden_hit.local_form_match)
        self.assertIn(
            TerminologyPolicyReasonCode.POLICY_FORBIDDEN_VARIANT_PRESENT,
            forbidden_hit.reason_codes,
        )

    def test_manual_review_mode_and_unimplemented_modes_never_claim_match(self):
        manual_policy = _policy(
            "terminology_policy.generic.manual",
            target_language="ja",
            match_mode=TerminologyMatchMode.MANUAL_REVIEW_REQUIRED,
            allowed_variant_strategy=AllowedVariantStrategy.MANUAL_REVIEW_ONLY,
            forbidden_variant_strategy=ForbiddenVariantStrategy.MANUAL_REVIEW_ONLY,
        )
        future_policy = _policy(
            "terminology_policy.generic.inflection",
            target_language="pl",
            match_mode=TerminologyMatchMode.INFLECTION_AWARE,
            allowed_variant_strategy=AllowedVariantStrategy.MANUAL_REVIEW_ONLY,
            forbidden_variant_strategy=ForbiddenVariantStrategy.MANUAL_REVIEW_ONLY,
        )

        manual = match_terminology_target(
            manual_policy,
            translated_text="Any local text.",
            target_canonical="Configured Form",
        )
        future = match_terminology_target(
            future_policy,
            translated_text="Any local text.",
            target_canonical="Configured Form",
        )

        self.assertEqual(manual.status, TerminologyMatchStatus.NEEDS_REVIEW)
        self.assertFalse(manual.checked)
        self.assertFalse(manual.local_form_match)
        self.assertIn(
            TerminologyPolicyReasonCode.POLICY_MANUAL_REVIEW_REQUIRED,
            manual.reason_codes,
        )
        self.assertEqual(future.status, TerminologyMatchStatus.NEEDS_REVIEW)
        self.assertFalse(future.checked)
        self.assertIn(
            TerminologyPolicyReasonCode.POLICY_UNIMPLEMENTED_MATCH_MODE,
            future.reason_codes,
        )
        self.assertIn(
            TerminologyPolicyReasonCode.MORPHOLOGY_POLICY_TBD,
            future.reason_codes,
        )

    def test_match_payload_is_metadata_only_and_excludes_raw_text(self):
        raw_translation = "RAW TRANSLATION MUST NOT SERIALIZE"
        raw_target = "RAW TARGET MUST NOT SERIALIZE"
        policy = _policy(
            "terminology_policy.generic.variant_list",
            target_language="es",
            match_mode=TerminologyMatchMode.VARIANT_LIST,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_AND_VARIANTS,
        )

        result = match_terminology_target(
            policy,
            translated_text=f"{raw_translation} with {raw_target}.",
            target_canonical=raw_target,
        )
        payload = terminology_match_payload(result)
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        self.assertEqual(payload["status"], "match")
        self.assertTrue(payload["metadata_only"])
        self.assertFalse(payload["raw_payload_included"])
        self.assertFalse(payload["semantic_quality_claim_made"])
        self.assertFalse(payload["full_morphology_claim_made"])
        self.assertIn("semantic_truth_not_proven", payload["reason_codes"])
        self.assertNotIn(raw_translation, serialized)
        self.assertNotIn(raw_target, serialized)

    def test_invalid_policy_match_payload_does_not_echo_bad_identifier(self):
        raw_identifier = "RAW POLICY IDENTIFIER MUST NOT SERIALIZE"
        policy = TerminologyPolicy(
            policy_id=raw_identifier,
            policy_version="",
            target_language="es",
            language_family=None,
            match_mode="invalid",
            normalization_mode=TerminologyNormalizationMode.NFC,
            allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_ONLY,
            forbidden_variant_strategy=ForbiddenVariantStrategy.IGNORE,
            unsupported_fallback=UnsupportedTerminologyFallback.MANUAL_REVIEW_REQUIRED,
            reason_codes=DEFAULT_TERMINOLOGY_POLICY_REASON_CODES,
        )

        result = match_terminology_target(
            policy,
            translated_text="Configured term appears here.",
            target_canonical="Configured term",
        )
        payload = terminology_match_payload(result)
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        self.assertEqual(result.status, TerminologyMatchStatus.INVALID_POLICY)
        self.assertIsNone(payload["policy_id"])
        self.assertIsNone(payload["policy_version"])
        self.assertIn("policy_data_invalid", payload["reason_codes"])
        self.assertNotIn(raw_identifier, serialized)


def _policy(
    policy_id: str,
    *,
    target_language: str | None,
    match_mode: TerminologyMatchMode,
    normalization_mode: TerminologyNormalizationMode = TerminologyNormalizationMode.NFC,
    allowed_variant_strategy: AllowedVariantStrategy,
    forbidden_variant_strategy: ForbiddenVariantStrategy = (
        ForbiddenVariantStrategy.IGNORE
    ),
    language_family: str | None = None,
) -> TerminologyPolicy:
    return TerminologyPolicy(
        policy_id=policy_id,
        policy_version="v1",
        target_language=target_language,
        language_family=language_family,
        match_mode=match_mode,
        normalization_mode=normalization_mode,
        allowed_variant_strategy=allowed_variant_strategy,
        forbidden_variant_strategy=forbidden_variant_strategy,
        unsupported_fallback=UnsupportedTerminologyFallback.MANUAL_REVIEW_REQUIRED,
        reason_codes=DEFAULT_TERMINOLOGY_POLICY_REASON_CODES,
    )


def _codes(result) -> set[TerminologyPolicyValidationCode]:
    return {issue.code for issue in result.issues}


if __name__ == "__main__":
    unittest.main()
