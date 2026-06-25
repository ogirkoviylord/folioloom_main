import json
import unittest

from translator_service.glossary_compliance import validate_glossary_compliance
from translator_service.glossary_terminology_policy import (
    DEFAULT_TERMINOLOGY_POLICY_REASON_CODES,
    AllowedVariantStrategy,
    ForbiddenVariantStrategy,
    TerminologyMatchMode,
    TerminologyNormalizationMode,
    TerminologyPolicy,
    TerminologyPolicyRegistry,
    UnsupportedTerminologyFallback,
)


def _entry(
    entry_id: str,
    *,
    source: str,
    target: str | None = None,
    aliases: tuple[str, ...] = (),
    target_variants: tuple[str, ...] = (),
    forbidden_variants: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "source_canonical": source,
        "aliases": aliases,
        "target_canonical": target,
        "target_variants": target_variants,
        "forbidden_variants": forbidden_variants,
    }


class GlossaryComplianceTest(unittest.TestCase):
    def test_full_hit_uses_source_terms_and_aliases(self):
        result = validate_glossary_compliance(
            [
                _entry("entry-north", source="North Door", target="Северница"),
                _entry(
                    "entry-salt",
                    source="Salt Thread",
                    aliases=("Thread-of-Salt",),
                    target_variants=("Солевязь",),
                ),
            ],
            selected_entry_ids=("entry-north", "entry-salt"),
            included_entry_ids=("entry-north", "entry-salt"),
            source_text="The North Door and Thread-of-Salt were marked.",
            translated_text="Северница и Солевязь были отмечены.",
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checked_entry_count"], 2)
        self.assertEqual(result["target_form_present_count"], 2)
        self.assertEqual(result["target_form_missing_count"], 0)
        self.assertEqual(result["skipped_entry_count"], 0)
        self.assertEqual(result["schema_version"], "glossary-compliance-v2")
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(
            result["target_form_present_entry_ids"],
            ["entry-north", "entry-salt"],
        )
        self.assertFalse(result["terminology_policy"]["enabled"])
        self.assertEqual(
            result["policy"],
            "exact_configured_target_forms_only_v1",
        )
        self.assertIn("morphology_policy_tbd", result["uncertainty_reason_codes"])

    def test_partial_and_zero_hits_are_findings_without_structural_failure(self):
        entries = [
            _entry("entry-north", source="North Door", target="Северница"),
            _entry("entry-salt", source="Salt Thread", target="Солевязь"),
            _entry("entry-absent", source="Absent Gate", target="Пропавшие Врата"),
            _entry("entry-omitted", source="Omitted Gate", target="Скрытые Врата"),
        ]
        partial = validate_glossary_compliance(
            entries,
            selected_entry_ids=(
                "entry-north",
                "entry-salt",
                "entry-absent",
                "entry-omitted",
            ),
            included_entry_ids=("entry-north", "entry-salt", "entry-absent"),
            source_text="North Door and Salt Thread.",
            translated_text="Северница была на месте, но второго термина нет.",
        )
        zero = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-north", "entry-salt"),
            included_entry_ids=("entry-north", "entry-salt"),
            source_text="North Door and Salt Thread.",
            translated_text="Ни одного настроенного термина тут нет.",
        )

        self.assertEqual(partial["status"], "findings")
        self.assertEqual(partial["target_form_present_entry_ids"], ["entry-north"])
        self.assertEqual(partial["target_form_missing_entry_ids"], ["entry-salt"])
        self.assertEqual(partial["requested_entry_count"], 4)
        self.assertEqual(partial["context_included_entry_count"], 3)
        self.assertEqual(partial["context_omitted_entry_count"], 1)
        self.assertEqual(
            partial["source_term_present_entry_ids"],
            ["entry-north", "entry-salt"],
        )
        self.assertEqual(partial["source_term_missing_entry_ids"], ["entry-absent"])
        self.assertEqual(partial["source_term_present_count"], 2)
        self.assertEqual(partial["source_term_missing_count"], 1)
        self.assertEqual(partial["observed_target_form_present_count"], 1)
        self.assertEqual(partial["observed_target_form_missing_count"], 1)
        self.assertEqual(
            partial["quality_evidence_scope"],
            "local_target_form_presence_only",
        )
        self.assertFalse(partial["quality_pass_fail_policy_changed"])
        self.assertTrue(partial["requested_effective_observed_separated"])
        self.assertFalse(partial["semantic_quality_claim_made"])
        self.assertIn("target_form_missing", partial["reason_codes"])
        self.assertIn("source_term_absent", partial["reason_codes"])
        self.assertIn("glossary_context_omitted", partial["reason_codes"])
        self.assertEqual(zero["status"], "findings")
        self.assertEqual(zero["target_form_present_count"], 0)
        self.assertEqual(zero["target_form_missing_count"], 2)
        serialized = json.dumps(partial, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("North Door and Salt Thread.", serialized)
        self.assertNotIn("Северница была на месте", serialized)

    def test_skip_reasons_and_structural_failure_are_metadata_only(self):
        entries = [
            _entry("entry-absent", source="Absent Term", target="Отсутствует"),
            _entry("entry-no-target", source="No Target"),
            _entry("entry-omitted", source="Omitted Term", target="Пропуск"),
        ]

        result = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-absent", "entry-no-target", "entry-omitted"),
            included_entry_ids=("entry-absent", "entry-no-target"),
            source_text="No Target and Omitted Term are present.",
            translated_text="Пропуск.",
        )
        structural_fail = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-absent",),
            included_entry_ids=("entry-absent",),
            source_text="Absent Term.",
            translated_text=None,
            structural_validation_passed=False,
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["checked_entry_count"], 0)
        self.assertEqual(result["skipped_entry_count"], 3)
        self.assertIn("source_term_absent", result["reason_codes"])
        self.assertIn("target_metadata_missing", result["reason_codes"])
        self.assertIn("glossary_context_omitted", result["reason_codes"])
        self.assertEqual(structural_fail["status"], "skipped")
        self.assertIn("structural_validation_failed", structural_fail["reason_codes"])

    def test_policy_variant_hit_and_forbidden_variant_are_metadata_only_findings(self):
        registry = TerminologyPolicyRegistry(
            (
                _policy(
                    "terminology_policy.ru.variant_list.test",
                    target_language="ru",
                    match_mode=TerminologyMatchMode.VARIANT_LIST,
                    allowed_variant_strategy=(
                        AllowedVariantStrategy.CANONICAL_AND_VARIANTS
                    ),
                    forbidden_variant_strategy=(
                        ForbiddenVariantStrategy.CONFIGURED_FORBIDDEN_VARIANTS
                    ),
                ),
            )
        )
        entries = [
            _entry(
                "entry-glass-market",
                source="Glass Market",
                aliases=("The Glass Market",),
                target="Зеркальный Торг",
                target_variants=("Зеркального Торга",),
                forbidden_variants=("Стеклянный рынок",),
            )
        ]

        approved_variant = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-glass-market",),
            included_entry_ids=("entry-glass-market",),
            source_text="The Glass Market opened at dusk.",
            translated_text="У Зеркального Торга собрались все.",
            target_language="ru",
            terminology_policy_registry=registry,
        )
        forbidden_variant = validate_glossary_compliance(
            entries,
            selected_entry_ids=("entry-glass-market",),
            included_entry_ids=("entry-glass-market",),
            source_text="The Glass Market opened at dusk.",
            translated_text="Стеклянный рынок открылся на закате.",
            target_language="ru",
            terminology_policy_registry=registry,
        )

        self.assertEqual(approved_variant["status"], "pass")
        self.assertEqual(
            approved_variant["policy"],
            "terminology_policy_registry_adapter_v1",
        )
        self.assertTrue(approved_variant["terminology_policy"]["enabled"])
        self.assertEqual(
            approved_variant["terminology_policy"]["policy_id"],
            "terminology_policy.ru.variant_list.test",
        )
        self.assertEqual(approved_variant["target_form_present_count"], 1)
        self.assertEqual(
            approved_variant["entries"][0]["terminology_match"]["matched_form_kind"],
            "variant",
        )
        self.assertIn(
            "policy_variant_match",
            approved_variant["entries"][0]["reason_codes"],
        )
        self.assertEqual(forbidden_variant["status"], "findings")
        self.assertEqual(forbidden_variant["forbidden_variant_count"], 1)
        self.assertEqual(
            forbidden_variant["forbidden_variant_entry_ids"],
            ["entry-glass-market"],
        )
        self.assertIn(
            "policy_forbidden_variant_present",
            forbidden_variant["reason_codes"],
        )
        self.assertEqual(
            forbidden_variant["entries"][0]["terminology_match"]["status"],
            "forbidden_variant",
        )

        serialized = json.dumps(
            {
                "approved": approved_variant,
                "forbidden": forbidden_variant,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn("The Glass Market opened at dusk.", serialized)
        self.assertNotIn("Зеркального Торга", serialized)
        self.assertNotIn("Стеклянный рынок", serialized)

    def test_policy_unsupported_and_manual_review_do_not_claim_pass(self):
        entry = _entry(
            "entry-needle-house",
            source="Needle House",
            target="Dom Igły",
        )
        unsupported = validate_glossary_compliance(
            [entry],
            selected_entry_ids=("entry-needle-house",),
            included_entry_ids=("entry-needle-house",),
            source_text="Needle House is mentioned here.",
            translated_text="Dom Igły appears here.",
            target_language="pl",
            terminology_policy_registry=TerminologyPolicyRegistry(()),
        )
        manual_review = validate_glossary_compliance(
            [entry],
            selected_entry_ids=("entry-needle-house",),
            included_entry_ids=("entry-needle-house",),
            source_text="Needle House is mentioned here.",
            translated_text="Dom Igły appears here.",
            target_language="pl",
            terminology_policy_registry=TerminologyPolicyRegistry(
                (
                    _policy(
                        "terminology_policy.pl.manual_review.test",
                        target_language="pl",
                        match_mode=TerminologyMatchMode.MANUAL_REVIEW_REQUIRED,
                        allowed_variant_strategy=(
                            AllowedVariantStrategy.MANUAL_REVIEW_ONLY
                        ),
                        forbidden_variant_strategy=(
                            ForbiddenVariantStrategy.MANUAL_REVIEW_ONLY
                        ),
                    ),
                )
            ),
        )

        self.assertEqual(unsupported["status"], "findings")
        self.assertEqual(unsupported["checked_entry_count"], 0)
        self.assertEqual(unsupported["needs_review_entry_count"], 1)
        self.assertIn("policy_unsupported_language", unsupported["reason_codes"])
        self.assertEqual(
            unsupported["entries"][0]["terminology_match"]["status"],
            "needs_review",
        )
        self.assertEqual(manual_review["status"], "findings")
        self.assertEqual(
            manual_review["needs_review_entry_ids"],
            ["entry-needle-house"],
        )
        self.assertIn("policy_manual_review_required", manual_review["reason_codes"])
        self.assertFalse(manual_review["semantic_quality_claim_made"])
        self.assertFalse(
            manual_review["entries"][0]["terminology_match"][
                "full_morphology_claim_made"
            ]
        )

    def test_metadata_payload_excludes_raw_source_target_and_translation_text(self):
        raw_source = "RAW SOURCE MUST NOT SERIALIZE"
        raw_target = "RAW TARGET MUST NOT SERIALIZE"
        raw_translation = "RAW TRANSLATION MUST NOT SERIALIZE"

        result = validate_glossary_compliance(
            [_entry("entry-safe", source=raw_source, target=raw_target)],
            selected_entry_ids=("entry-safe",),
            included_entry_ids=("entry-safe",),
            source_text=f"{raw_source} appears here.",
            translated_text=f"{raw_translation} appears here.",
        )

        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn(raw_target, serialized)
        self.assertNotIn(raw_translation, serialized)
        self.assertTrue(result["metadata_only"])
        self.assertFalse(result["raw_payload_included"])
        self.assertFalse(result["semantic_quality_claim_made"])


def _policy(
    policy_id: str,
    *,
    target_language: str | None,
    match_mode: TerminologyMatchMode,
    allowed_variant_strategy: AllowedVariantStrategy,
    forbidden_variant_strategy: ForbiddenVariantStrategy = (
        ForbiddenVariantStrategy.IGNORE
    ),
) -> TerminologyPolicy:
    return TerminologyPolicy(
        policy_id=policy_id,
        policy_version="v1",
        target_language=target_language,
        language_family=None,
        match_mode=match_mode,
        normalization_mode=TerminologyNormalizationMode.NFC,
        allowed_variant_strategy=allowed_variant_strategy,
        forbidden_variant_strategy=forbidden_variant_strategy,
        unsupported_fallback=UnsupportedTerminologyFallback.MANUAL_REVIEW_REQUIRED,
        reason_codes=DEFAULT_TERMINOLOGY_POLICY_REASON_CODES,
    )


if __name__ == "__main__":
    unittest.main()
