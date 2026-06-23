import unittest
from collections.abc import Mapping
from typing import Any

from translator_service.content_roles import (
    BEHAVIOR_RISK_APPROVAL_FLAGS,
    SECTION_BLOCK_ACTION_ENVELOPE,
    TOKEN_ACTION_ENVELOPE,
    ContentRoleAnnotation,
    TokenPreservationMetadata,
    content_role_evidence_from_metadata,
    content_role_metadata_pairs,
    source_locator_from_metadata,
)

SYNTHETIC_METADATA_CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "synthetic-epub-section-rights",
        "locator": {
            "surface": "epub_xhtml_body",
            "source_path_or_chunk_id": "epub:synthetic:rights-section:1",
            "granularity": "section",
            "structure_hints": ["frontmatter", "rights-section"],
            "position_hint": "front",
        },
        "role": "legal_rights_boilerplate",
        "confidence": "high",
        "reporting_bucket": "legal_archive_shadow",
        "expected_envelope": SECTION_BLOCK_ACTION_ENVELOPE,
        "evidence": (
            {
                "signal_family": "structural_semantic",
                "strength": "strong",
                "metadata_value_kind": "synthetic_epub_landmark",
                "reason_code": "rights_section_landmark",
            },
            {
                "signal_family": "body_lexical_cluster",
                "strength": "medium",
                "metadata_value_kind": "synthetic_phrase_cluster",
                "reason_code": "rights_boilerplate_cluster",
            },
        ),
    },
    {
        "case_id": "synthetic-docx-block-publisher",
        "locator": {
            "surface": "docx_paragraph",
            "source_path_or_chunk_id": "docx:word/document.xml:publisher-block:2",
            "granularity": "block",
            "structure_hints": ["paragraph", "publisher-metadata"],
            "position_hint": "front",
        },
        "role": "publisher_metadata",
        "confidence": "medium",
        "reporting_bucket": "publisher_metadata_shadow",
        "expected_envelope": SECTION_BLOCK_ACTION_ENVELOPE,
        "evidence": (
            {
                "signal_family": "structural_semantic",
                "strength": "medium",
                "metadata_value_kind": "synthetic_docx_style",
                "reason_code": "publisher_metadata_paragraph",
            },
        ),
    },
    {
        "case_id": "synthetic-txt-token-catalog-id",
        "locator": {
            "surface": "txt_line",
            "source_path_or_chunk_id": "txt:synthetic-line:catalog-token:3",
            "granularity": "token",
            "structure_hints": ["line", "identifier-token"],
            "position_hint": "back",
        },
        "role": "publisher_metadata",
        "confidence": "medium",
        "reporting_bucket": "token_identifier",
        "expected_envelope": TOKEN_ACTION_ENVELOPE,
        "token_kinds": ("catalog_id",),
        "evidence": (
            {
                "signal_family": "url_or_rights_pattern",
                "strength": "medium",
                "metadata_value_kind": "synthetic_catalog_identifier",
                "reason_code": "catalog_identifier_token",
            },
        ),
    },
)

IDENTIFIER_TOKEN_CASES = (
    ("url", "epub_opf_metadata", "epub:opf:url-token:1"),
    ("isbn", "epub_opf_metadata", "epub:opf:isbn-token:2"),
    ("email", "docx_footer", "docx:word/footer1.xml:email-token:3"),
    ("catalog_id", "txt_line", "txt:line:catalog-token:4"),
)

FORBIDDEN_SERIALIZED_VALUE_FRAGMENTS = (
    "source_text",
    "translated_text",
    "provider_request",
    "provider_response",
    "raw_provider_response",
    "raw_translation",
    "prompt_body",
    "secret",
)


def _annotation_from_case(case: Mapping[str, Any]) -> ContentRoleAnnotation:
    locator = source_locator_from_metadata(case["locator"])
    evidence = tuple(
        content_role_evidence_from_metadata(signal) for signal in case["evidence"]
    )
    token_kinds = tuple(case.get("token_kinds", ()))
    return ContentRoleAnnotation(
        locator=locator,
        role=str(case["role"]),
        confidence=str(case["confidence"]),
        evidence=evidence,
        reporting_bucket=str(case["reporting_bucket"]),
        token_preservation=(
            TokenPreservationMetadata(token_kinds=token_kinds)
            if token_kinds
            else None
        ),
    )


class ContentRoleSourceLocatorContractTest(unittest.TestCase):
    def test_synthetic_metadata_constructs_deterministic_locators_and_evidence(self):
        observed_granularities = set()

        for case in SYNTHETIC_METADATA_CASES:
            with self.subTest(case_id=case["case_id"]):
                annotation = _annotation_from_case(case)
                metadata = annotation.to_metadata_dict()

                self.assertEqual(metadata["locator"], case["locator"])
                self.assertEqual(
                    metadata["evidence"],
                    [dict(signal) for signal in case["evidence"]],
                )
                self.assertEqual(
                    metadata["allowed_action_envelope"],
                    case["expected_envelope"],
                )
                observed_granularities.add(metadata["locator"]["granularity"])

        self.assertEqual(observed_granularities, {"section", "block", "token"})

    def test_url_isbn_email_and_catalog_identifiers_remain_token_scoped(self):
        for token_kind, surface, source_path_or_chunk_id in IDENTIFIER_TOKEN_CASES:
            with self.subTest(token_kind=token_kind):
                annotation = ContentRoleAnnotation(
                    locator=source_locator_from_metadata(
                        {
                            "surface": surface,
                            "source_path_or_chunk_id": source_path_or_chunk_id,
                            "granularity": "token",
                            "structure_hints": ["identifier-token"],
                            "position_hint": "metadata",
                        }
                    ),
                    role="publisher_metadata",
                    confidence="medium",
                    evidence=(
                        content_role_evidence_from_metadata(
                            {
                                "signal_family": "url_or_rights_pattern",
                                "strength": "medium",
                                "metadata_value_kind": f"synthetic_{token_kind}",
                                "reason_code": f"{token_kind}_token_identifier",
                            }
                        ),
                    ),
                    reporting_bucket="token_identifier",
                    token_preservation=TokenPreservationMetadata(
                        token_kinds=(token_kind,)
                    ),
                )

                metadata = annotation.to_metadata_dict()

                self.assertEqual(metadata["locator"]["granularity"], "token")
                self.assertEqual(
                    metadata["allowed_action_envelope"],
                    TOKEN_ACTION_ENVELOPE,
                )
                self.assertEqual(metadata["reporting_bucket"], "token_identifier")
                self.assertTrue(metadata["token_preservation"]["token_scope_only"])
                self.assertFalse(
                    metadata["token_preservation"][
                        "section_omit_or_preserve_allowed"
                    ]
                )
                self.assertEqual(
                    metadata["token_preservation"]["token_kinds"], [token_kind]
                )

    def test_context_clues_alone_cannot_produce_high_confidence_legal_roles(self):
        locator = source_locator_from_metadata(
            {
                "surface": "epub_opf_metadata",
                "source_path_or_chunk_id": "epub:opf:source-position-path-only:1",
                "granularity": "block",
                "structure_hints": ["publisher", "metadata"],
                "position_hint": "front",
            }
        )
        weak_context_signals = (
            {
                "signal_family": "provenance_source_clue",
                "strength": "strong",
                "metadata_value_kind": "synthetic_source_name",
                "reason_code": "publisher_source_name_alone",
            },
            {
                "signal_family": "path_class_id",
                "strength": "strong",
                "metadata_value_kind": "synthetic_path_class",
                "reason_code": "path_alone",
            },
            {
                "signal_family": "position_layout",
                "strength": "strong",
                "metadata_value_kind": "synthetic_position",
                "reason_code": "position_alone",
            },
        )

        for signal_count in (1, 2, 3):
            for role in ("legal_rights_boilerplate", "archive_digitization_artifact"):
                with self.subTest(signal_count=signal_count, role=role):
                    with self.assertRaises(ValueError):
                        ContentRoleAnnotation(
                            locator=locator,
                            role=role,
                            confidence="high",
                            evidence=tuple(
                                content_role_evidence_from_metadata(signal)
                                for signal in weak_context_signals[:signal_count]
                            ),
                            reporting_bucket="legal_archive_shadow",
                        )

    def test_serialization_stays_metadata_only_and_behavior_neutral(self):
        for case in SYNTHETIC_METADATA_CASES:
            with self.subTest(case_id=case["case_id"]):
                metadata = _annotation_from_case(case).to_metadata_dict()

                self.assertFalse(metadata["behavior_allowed"])
                self.assertFalse(metadata["raw_publication_allowed"])
                self.assertEqual(
                    set(metadata["risk_approval_flags"]),
                    set(BEHAVIOR_RISK_APPROVAL_FLAGS),
                )
                self.assertTrue(
                    all(
                        value is False
                        for value in metadata["risk_approval_flags"].values()
                    )
                )
                serialized = str(metadata).lower()
                for forbidden in FORBIDDEN_SERIALIZED_VALUE_FRAGMENTS:
                    self.assertNotIn(forbidden, serialized)

    def test_reader_navigation_annotation_pairs_are_namespaced_scalar_contract(self):
        annotation = ContentRoleAnnotation(
            locator=source_locator_from_metadata(
                {
                    "surface": "epub_xhtml_nav",
                    "source_path_or_chunk_id": (
                        "epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0"
                    ),
                    "granularity": "block",
                    "structure_hints": ["xhtml-navigation", "reader-navigation"],
                    "position_hint": "auxiliary",
                }
            ),
            role="reader_navigation",
            confidence="high",
            evidence=(
                content_role_evidence_from_metadata(
                    {
                        "signal_family": "structural_semantic",
                        "strength": "strong",
                        "metadata_value_kind": "xhtml_nav_element",
                        "reason_code": "epub_xhtml_navigation_auxiliary_block",
                    }
                ),
                content_role_evidence_from_metadata(
                    {
                        "signal_family": "path_class_id",
                        "strength": "medium",
                        "metadata_value_kind": "epub_aux_kind",
                        "reason_code": "xhtml_navigation_aux_kind",
                    }
                ),
            ),
            reporting_bucket="reader_visible",
        )

        pairs = content_role_metadata_pairs(annotation)
        metadata = dict(pairs)

        self.assertEqual(
            metadata,
            {
                "content_role.schema_version": "content-role-annotation-v1",
                "content_role.source_surface": "epub_xhtml_nav",
                "content_role.source_granularity": "block",
                "content_role.role": "reader_navigation",
                "content_role.confidence": "high",
                "content_role.reporting_bucket": "reader_visible",
                "content_role.allowed_action_envelope": (
                    "shadow_report_translate_include"
                ),
                "content_role.behavior_allowed": "false",
                "content_role.raw_publication_allowed": "false",
                "content_role.risk_approval_flags": "all_false",
                "content_role.evidence_signal_families": (
                    "path_class_id,structural_semantic"
                ),
                "content_role.evidence_reason_codes": (
                    "epub_xhtml_navigation_auxiliary_block,xhtml_navigation_aux_kind"
                ),
            },
        )
        self.assertTrue(all(key.startswith("content_role.") for key, _ in pairs))
        self.assertTrue(all(isinstance(value, str) for _, value in pairs))
        serialized = str(pairs).lower()
        for forbidden in FORBIDDEN_SERIALIZED_VALUE_FRAGMENTS:
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
