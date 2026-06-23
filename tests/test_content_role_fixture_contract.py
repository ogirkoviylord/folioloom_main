import copy
import json
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from translator_service import content_roles

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "test_samples"
    / "content_roles"
    / "content_role_fixture_matrix.json"
)

REQUIRED_NEGATIVE_FIXTURE_IDS = {
    "cr-neg-legal-word-fiction-dialogue-v1",
    "cr-neg-copyright-discussion-chapter-v1",
    "cr-neg-legal-discussion-preface-v1",
    "cr-neg-archive-ocr-words-main-content-v1",
    "cr-neg-toc-title-legal-archive-terms-v1",
    "cr-neg-rights-attributed-epigraph-v1",
    "cr-neg-editorial-transcriber-note-v1",
    "cr-neg-url-only-section-v1",
    "cr-neg-publisher-source-name-only-v1",
    "cr-neg-position-only-front-back-matter-v1",
    "cr-neg-ambiguous-mixed-paragraph-v1",
    "cr-neg-scholarly-note-copyright-archive-v1",
    "cr-neg-publisher-colophon-identifiers-v1",
}

REQUIRED_POSITIVE_FIXTURE_IDS = {
    "cr-pos-legal-rights-boilerplate-epub-v1",
    "cr-pos-legal-rights-boilerplate-docx-v1",
    "cr-pos-archive-digitization-artifact-epub-v1",
    "cr-pos-archive-digitization-artifact-txt-v1",
    "cr-pos-publisher-metadata-separate-v1",
}

FORBIDDEN_FIELD_NAMES = {
    "api_key",
    "authorization",
    "auth_material",
    "owner_only_diagnostics",
    "password",
    "private_diagnostics",
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
    "<translation_batch",
    "Authorization:",
    "Bearer ",
    "Project Gutenberg",
    "RAW PROVIDER",
    "RAW SOURCE",
    "RAW TARGET",
    "RAW TRANSLATION",
    "owner_policy_tbd_later_behavior",
    "sk-",
)

RISK_APPROVAL_FLAGS = set(content_roles.BEHAVIOR_RISK_APPROVAL_FLAGS)

ALLOWED_RAW_SAFETY_FLAG_NAMES = {
    "raw_excerpt_included",
    "raw_publication_allowed",
}

DISALLOWED_SINGLE_SIGNAL_SHORTCUTS = {
    "publisher_source_name_alone",
    "position_alone",
    "path_alone",
    "url_alone",
    "all_caps_alone",
    "one_broad_word",
    "cache_or_output_side_text_alone",
    "project_gutenberg_or_source_specific_key",
}

LEGAL_ARCHIVE_ROLES = {
    "legal_rights_boilerplate",
    "archive_digitization_artifact",
}

SECTION_BEHAVIOR_FORBIDDEN_TERMS = (
    "omit",
    "preserve_verbatim",
    "section_preserve",
    "exempt",
    "exclude",
    "skip_translation",
)


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise AssertionError("fixture root must be a JSON object")
    return payload


def _fixture_cases(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases = payload["cases"]
    if not isinstance(cases, list):
        raise AssertionError("fixture cases must be a JSON array")
    return cases


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


class ContentRoleFixtureContractTest(unittest.TestCase):
    def test_fixture_matrix_contains_required_metadata_only_cases(self):
        fixture = _load_fixture()
        self.assertEqual(
            fixture["schema_version"],
            content_roles.FIXTURE_SCHEMA_VERSION,
        )
        self.assertEqual(fixture["fixture_id"], "content-role-fixture-matrix-v1")
        self.assertTrue(fixture["metadata_safety"]["metadata_only"])
        self.assertFalse(fixture["metadata_safety"]["raw_publication_allowed"])

        cases = _fixture_cases(fixture)
        fixture_ids = {case["fixture_id"] for case in cases}
        self.assertEqual(len(fixture_ids), len(cases))
        self.assertTrue(REQUIRED_NEGATIVE_FIXTURE_IDS <= fixture_ids)
        self.assertTrue(REQUIRED_POSITIVE_FIXTURE_IDS <= fixture_ids)

        for case in cases:
            with self.subTest(fixture_id=case["fixture_id"]):
                self.assertEqual(
                    set(content_roles.REQUIRED_FIXTURE_CASE_FIELDS),
                    set(content_roles.REQUIRED_FIXTURE_CASE_FIELDS) & set(case),
                )
                self.assertIn(case["format_surface"], content_roles.FORMAT_SURFACES)
                self.assertIn(case["expected_role"], content_roles.ALLOWED_ROLES)
                self.assertIn(
                    case["expected_confidence"],
                    content_roles.CONFIDENCE_LEVELS,
                )
                self.assertIn(
                    case["reporting_bucket"],
                    content_roles.REPORTING_BUCKETS,
                )
                self.assertFalse(case["behavior_allowed"])
                self.assertFalse(case["raw_publication_allowed"])
                self.assertEqual(
                    case["schema_version"],
                    content_roles.FIXTURE_SCHEMA_VERSION,
                )
                self.assertEqual(
                    case["allowed_action_envelope"],
                    content_roles.SECTION_BLOCK_ACTION_ENVELOPE,
                )
                self.assertEqual(content_roles.validate_fixture_case(case), ())
                self.assertEqual(
                    set(content_roles.REQUIRED_SOURCE_STRUCTURE_FIELDS),
                    set(content_roles.REQUIRED_SOURCE_STRUCTURE_FIELDS)
                    & set(case["source_structure"]),
                )
                self.assertEqual(
                    set(content_roles.REQUIRED_TEXT_SNIPPET_POLICY_FIELDS),
                    set(content_roles.REQUIRED_TEXT_SNIPPET_POLICY_FIELDS)
                    & set(case["text_snippet_policy"]),
                )
                self.assertIn(
                    case["source_structure"]["surface"],
                    content_roles.SOURCE_SURFACES,
                )
                self.assertIn(
                    case["source_structure"]["granularity"],
                    content_roles.GRANULARITIES,
                )
                self.assertFalse(case["text_snippet_policy"]["raw_excerpt_included"])
                self.assertFalse(
                    case["text_snippet_policy"]["private_or_copyrighted_source_allowed"]
                )
                self.assertNotIn("owner_policy_tbd_later_behavior", json.dumps(case))

    def test_validate_fixture_case_catches_invalid_violations(self):
        fixture = _load_fixture()
        base_case = _fixture_cases(fixture)[0]

        def assert_invalid(mutator, expected_fragment: str) -> None:
            invalid_case = copy.deepcopy(base_case)
            mutator(invalid_case)

            errors = content_roles.validate_fixture_case(invalid_case)

            self.assertTrue(errors)
            self.assertTrue(
                any(expected_fragment in error for error in errors),
                f"expected {expected_fragment!r} in errors: {errors!r}",
            )

        mutations = (
            (
                "schema_version",
                lambda case: case.__setitem__("schema_version", "wrong-version"),
                "schema_version",
            ),
            (
                "format_surface",
                lambda case: case.__setitem__("format_surface", "invalid_format"),
                "format_surface",
            ),
            (
                "expected_role",
                lambda case: case.__setitem__("expected_role", "invalid_role"),
                "expected_role",
            ),
            (
                "expected_confidence",
                lambda case: case.__setitem__("expected_confidence", "invalid_conf"),
                "expected_confidence",
            ),
            (
                "reporting_bucket",
                lambda case: case.__setitem__("reporting_bucket", "invalid_bucket"),
                "reporting_bucket",
            ),
            (
                "missing_required_field",
                lambda case: case.pop("fixture_id"),
                "missing required fields",
            ),
            (
                "behavior_allowed",
                lambda case: case.__setitem__("behavior_allowed", True),
                "behavior_allowed",
            ),
            (
                "raw_publication_allowed",
                lambda case: case.__setitem__("raw_publication_allowed", True),
                "raw_publication_allowed",
            ),
            (
                "allowed_action_envelope",
                lambda case: case.__setitem__(
                    "allowed_action_envelope",
                    "wrong_envelope",
                ),
                "action envelope",
            ),
            (
                "token_action_envelope",
                lambda case: case["protected_token_expectations"].__setitem__(
                    "token_action_envelope",
                    "wrong",
                ),
                "protected-token action",
            ),
            (
                "section_omit_or_preserve_allowed",
                lambda case: case["protected_token_expectations"].__setitem__(
                    "section_omit_or_preserve_allowed",
                    True,
                ),
                "section behavior",
            ),
            (
                "high_confidence_positive_signals",
                lambda case: case.__setitem__("positive_signals", []),
                "high confidence requires",
            ),
            (
                "positive_signal_strength",
                lambda case: case["positive_signals"][0].__setitem__(
                    "strength",
                    "owner_policy_tbd_later_behavior",
                ),
                "positive_signals strength",
            ),
        )

        for field_name, mutator, expected_fragment in mutations:
            with self.subTest(field_name=field_name):
                assert_invalid(mutator, expected_fragment)

    def test_action_vocabulary_is_canonical_and_metadata_only(self):
        self.assertEqual(
            content_roles.SECTION_BLOCK_ACTION_ENVELOPE,
            "shadow_report_translate_include",
        )
        self.assertEqual(content_roles.TOKEN_ACTION_ENVELOPE, "token_preserve_only")
        self.assertNotIn(
            "owner_policy_tbd_later_behavior",
            content_roles.ALLOWED_ACTION_ENVELOPES,
        )
        self.assertEqual(
            content_roles.ALLOWED_ACTION_ENVELOPES,
            (
                content_roles.SECTION_BLOCK_ACTION_ENVELOPE,
                content_roles.TOKEN_ACTION_ENVELOPE,
            ),
        )

        fixture = _load_fixture()
        for case in _fixture_cases(fixture):
            with self.subTest(fixture_id=case["fixture_id"]):
                envelope = case["allowed_action_envelope"]
                self.assertEqual(envelope, content_roles.SECTION_BLOCK_ACTION_ENVELOPE)
                self.assertEqual(
                    case["fallback_expected"],
                    "translate_include_report_only",
                )
                protected = case["protected_token_expectations"]
                self.assertEqual(
                    protected["token_action_envelope"],
                    content_roles.TOKEN_ACTION_ENVELOPE,
                )
                self.assertTrue(protected["token_preserve_allowed"])
                self.assertFalse(protected["section_omit_or_preserve_allowed"])
                for term in SECTION_BEHAVIOR_FORBIDDEN_TERMS:
                    self.assertNotIn(term, envelope)
                    self.assertNotIn(term, case["fallback_expected"])

    def test_fixture_contains_no_raw_prompt_provider_secret_or_private_material(self):
        fixture = _load_fixture()
        self._assert_no_forbidden_fields(fixture)

        for value in _walk_values(fixture):
            if isinstance(value, str):
                self.assertNotIn("\n", value)
                self.assertLessEqual(len(value), 280)
                for sentinel in FORBIDDEN_VALUE_SENTINELS:
                    self.assertNotIn(sentinel, value)

    def test_high_confidence_requires_multiple_independent_signal_families(self):
        fixture = _load_fixture()
        shortcuts = set(fixture["single_signal_high_confidence_disallowed"])
        self.assertEqual(shortcuts, DISALLOWED_SINGLE_SIGNAL_SHORTCUTS)

        for case in _fixture_cases(fixture):
            with self.subTest(fixture_id=case["fixture_id"]):
                families = {
                    signal["signal_family"] for signal in case["positive_signals"]
                }
                self.assertTrue(families <= set(content_roles.SIGNAL_FAMILIES))
                shortcut_families = set(case["single_signal_shortcuts_rejected"])
                self.assertTrue(shortcut_families <= DISALLOWED_SINGLE_SIGNAL_SHORTCUTS)

                if case["expected_confidence"] == "high":
                    self.assertGreaterEqual(len(families), 2)
                    self.assertTrue(
                        content_roles.STRONG_HIGH_CONFIDENCE_FAMILIES & families
                    )
                    self.assertFalse(shortcut_families & families)

                if case["expected_role"] in LEGAL_ARCHIVE_ROLES:
                    self.assertFalse(
                        shortcut_families & DISALLOWED_SINGLE_SIGNAL_SHORTCUTS
                        and len(families) < 2
                    )

    def test_high_confidence_fixture_validation_rejects_all_weak_evidence(self):
        fixture = _load_fixture()
        invalid_case = copy.deepcopy(_fixture_cases(fixture)[0])
        invalid_case["expected_confidence"] = "high"
        invalid_case["positive_signals"] = (
            {
                "signal_family": "structural_semantic",
                "strength": "weak",
                "metadata_value_kind": "epub_type",
                "reason_code": "copyright_page_landmark",
            },
            {
                "signal_family": "body_lexical_cluster",
                "strength": "weak",
                "metadata_value_kind": "lexical_cluster",
                "reason_code": "rights_license_cluster",
            },
        )

        errors = content_roles.validate_fixture_case(invalid_case)

        self.assertTrue(errors)
        self.assertTrue(
            any("high confidence requires" in error for error in errors),
            f"expected high-confidence error in errors: {errors!r}",
        )

    def test_negative_cases_never_authorize_behavior_or_section_preservation(self):
        fixture = _load_fixture()
        negative_cases = [
            case
            for case in _fixture_cases(fixture)
            if case["fixture_id"].startswith("cr-neg-")
        ]
        self.assertEqual(len(negative_cases), len(REQUIRED_NEGATIVE_FIXTURE_IDS))

        for case in negative_cases:
            with self.subTest(fixture_id=case["fixture_id"]):
                self.assertFalse(case["behavior_allowed"])
                self.assertEqual(
                    case["allowed_action_envelope"],
                    content_roles.SECTION_BLOCK_ACTION_ENVELOPE,
                )
                self.assertNotEqual(case["expected_role"], "legal_rights_boilerplate")
                self.assertFalse(
                    case["expected_role"] == "archive_digitization_artifact"
                    and case["expected_confidence"] == "high"
                )
                self.assertIn(
                    case["conflict_rule_expected"],
                    content_roles.CONFLICT_RULES,
                )
                self.assertFalse(
                    case["protected_token_expectations"]["section_omit_or_preserve_allowed"]
                )
                behavior_values = (
                    case["allowed_action_envelope"],
                    case["fallback_expected"],
                    case["conflict_rule_expected"],
                    case["reporting_bucket"],
                )
                for term in SECTION_BEHAVIOR_FORBIDDEN_TERMS:
                    for value in behavior_values:
                        self.assertNotIn(term, value)

    def test_behavior_risk_approval_flags_are_false(self):
        fixture = _load_fixture()
        flags = fixture["risk_approval_flags"]
        self.assertEqual(set(flags), RISK_APPROVAL_FLAGS)
        for flag_name, value in flags.items():
            with self.subTest(flag_name=flag_name):
                self.assertFalse(value)

    def _assert_no_forbidden_fields(self, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized_key = str(key).strip().lower()
                self.assertNotIn(normalized_key, FORBIDDEN_FIELD_NAMES)
                if normalized_key not in ALLOWED_RAW_SAFETY_FLAG_NAMES:
                    self.assertFalse(normalized_key.startswith("raw_"))
                self._assert_no_forbidden_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                self._assert_no_forbidden_fields(nested)


if __name__ == "__main__":
    unittest.main()
