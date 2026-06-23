import unittest

from translator_service.content_roles import (
    BEHAVIOR_RISK_APPROVAL_FLAGS,
    REPORTING_BUCKETS,
    ContentRoleAnnotation,
    ContentRoleEvidence,
    SourceLocator,
    TokenPreservationMetadata,
    build_content_role_shadow_report,
    content_role_shadow_report_payload,
    report_bucket_metadata,
    reporting_bucket_for_annotation,
)


class ContentRoleReportingContractTest(unittest.TestCase):
    def test_roles_and_granularity_map_to_report_buckets_deterministically(self):
        cases = (
            ("main_content", "section", (), "main"),
            ("title_heading", "section", (), "reader_visible"),
            ("reader_navigation", "block", (), "reader_visible"),
            ("reader_visible_paratext", "block", (), "reader_visible"),
            ("legal_rights_boilerplate", "block", (), "legal_archive_shadow"),
            ("archive_digitization_artifact", "section", (), "legal_archive_shadow"),
            ("publisher_metadata", "block", (), "publisher_metadata_shadow"),
            ("unknown_paratext", "token", (), "unknown_shadow"),
            ("publisher_metadata", "token", ("isbn",), "token_identifier"),
        )

        observed_buckets = set()
        for role, granularity, token_kinds, expected_bucket in cases:
            with self.subTest(role=role, granularity=granularity):
                bucket = reporting_bucket_for_annotation(
                    role=role,
                    granularity=granularity,
                    token_kinds=token_kinds,
                )
                self.assertEqual(bucket, expected_bucket)
                observed_buckets.add(bucket)

        self.assertEqual(observed_buckets, set(REPORTING_BUCKETS))

    def test_report_bucket_metadata_serializes_only_descriptive_false_flags(self):
        for role, granularity, token_kinds in (
            ("main_content", "block", ()),
            ("reader_visible_paratext", "block", ()),
            ("legal_rights_boilerplate", "block", ()),
            ("publisher_metadata", "block", ()),
            ("unknown_paratext", "block", ()),
            ("publisher_metadata", "token", ("catalog_identifier",)),
        ):
            with self.subTest(role=role, granularity=granularity):
                metadata = report_bucket_metadata(
                    role=role,
                    granularity=granularity,
                    token_kinds=token_kinds,
                )

                self.assertTrue(metadata["metadata_only"])
                self.assertIn(metadata["reporting_bucket"], REPORTING_BUCKETS)
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
                self.assertNotIn("source_text", serialized)
                self.assertNotIn("translated_text", serialized)
                self.assertNotIn("provider_request", serialized)
                self.assertNotIn("raw_provider_response", serialized)
                self.assertNotIn("secret", serialized)

    def test_annotation_rejects_bucket_that_does_not_match_descriptive_contract(self):
        locator = SourceLocator(
            surface="epub_xhtml_body",
            source_path_or_chunk_id="epub:body:chapter:1",
            granularity="block",
            structure_hints=("chapter",),
            position_hint="body",
        )
        evidence = (
            ContentRoleEvidence(
                signal_family="structural_semantic",
                strength="strong",
                metadata_value_kind="epub_type",
                reason_code="chapter_body",
            ),
        )

        with self.assertRaises(ValueError):
            ContentRoleAnnotation(
                locator=locator,
                role="main_content",
                confidence="medium",
                evidence=evidence,
                reporting_bucket="legal_archive_shadow",
            )

    def test_token_identifier_bucket_requires_token_identifier_metadata(self):
        locator = SourceLocator(
            surface="epub_opf_metadata",
            source_path_or_chunk_id="epub:opf:identifier:isbn",
            granularity="token",
            structure_hints=("identifier",),
            position_hint="metadata",
        )
        evidence = (
            ContentRoleEvidence(
                signal_family="structural_semantic",
                strength="strong",
                metadata_value_kind="opf_dc_field",
                reason_code="publisher_identifier_field",
            ),
        )

        with self.assertRaises(ValueError):
            ContentRoleAnnotation(
                locator=locator,
                role="publisher_metadata",
                confidence="medium",
                evidence=evidence,
                reporting_bucket="publisher_metadata_shadow",
                token_preservation=TokenPreservationMetadata(token_kinds=("isbn",)),
            )

    def test_shadow_report_aggregates_only_safe_content_role_metadata(self):
        report = build_content_role_shadow_report(
            (
                {
                    "content_role.source_surface": "epub_xhtml_nav",
                    "content_role.source_granularity": "block",
                    "content_role.role": "reader_navigation",
                    "content_role.confidence": "high",
                    "content_role.reporting_bucket": "reader_visible",
                    "content_role.behavior_allowed": "false",
                    "content_role.raw_publication_allowed": "false",
                },
                {
                    "content_role.source_surface": "epub_opf_metadata",
                    "content_role.source_granularity": "block",
                    "content_role.role": "publisher_metadata",
                    "content_role.confidence": "medium",
                    "content_role.reporting_bucket": "publisher_metadata_shadow",
                    "content_role.behavior_allowed": "false",
                    "content_role.raw_publication_allowed": "false",
                    "raw_source": "PRIVATE_SOURCE_SENTINEL",
                },
                {"unrelated": "metadata"},
            )
        )
        payload = content_role_shadow_report_payload(report)
        serialized = str(payload).lower()

        self.assertEqual(payload["schema_version"], "content-role-shadow-report-v1")
        self.assertTrue(payload["metadata_only"])
        self.assertFalse(payload["behavior_allowed"])
        self.assertFalse(payload["raw_publication_allowed"])
        self.assertEqual(payload["annotated_block_count"], 2)
        self.assertEqual(
            payload["bucket_counts"],
            {"publisher_metadata_shadow": 1, "reader_visible": 1},
        )
        self.assertEqual(payload["confidence_counts"], {"high": 1, "medium": 1})
        self.assertEqual(
            payload["source_surface_counts"],
            {"epub_opf_metadata": 1, "epub_xhtml_nav": 1},
        )
        self.assertEqual(payload["unknown_annotation_count"], 0)
        self.assertEqual(payload["conflicting_safety_flag_count"], 0)
        self.assertNotIn("private_source_sentinel", serialized)
        self.assertNotIn("raw_source", serialized)

    def test_shadow_report_counts_unknown_and_conflicts_without_raw_values(self):
        report = build_content_role_shadow_report(
            (
                (
                    ("content_role.source_surface", "unknown"),
                    ("content_role.source_granularity", "block"),
                    ("content_role.role", "unknown_paratext"),
                    ("content_role.confidence", "unknown"),
                    ("content_role.reporting_bucket", "unknown_shadow"),
                    ("content_role.behavior_allowed", "true"),
                    ("content_role.raw_publication_allowed", "true"),
                    ("content_role.evidence_reason_codes", "raw source excerpt here"),
                ),
            )
        )
        payload = content_role_shadow_report_payload(report)
        serialized = str(payload).lower()

        self.assertEqual(payload["annotated_block_count"], 1)
        self.assertEqual(payload["unknown_annotation_count"], 1)
        self.assertEqual(payload["conflicting_safety_flag_count"], 1)
        self.assertEqual(payload["bucket_counts"], {"unknown_shadow": 1})
        self.assertEqual(payload["confidence_counts"], {"unknown": 1})
        self.assertNotIn("raw source excerpt", serialized)
        self.assertNotIn("evidence_reason_codes", serialized)


if __name__ == "__main__":
    unittest.main()
