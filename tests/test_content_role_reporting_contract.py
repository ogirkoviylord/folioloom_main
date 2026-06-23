import unittest

from translator_service.content_roles import (
    BEHAVIOR_RISK_APPROVAL_FLAGS,
    REPORTING_BUCKETS,
    ContentRoleAnnotation,
    ContentRoleEvidence,
    SourceLocator,
    TokenPreservationMetadata,
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


if __name__ == "__main__":
    unittest.main()
