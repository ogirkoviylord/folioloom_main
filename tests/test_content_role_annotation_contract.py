import unittest

from translator_service.content_roles import (
    BEHAVIOR_RISK_APPROVAL_FLAGS,
    SECTION_BLOCK_ACTION_ENVELOPE,
    TOKEN_ACTION_ENVELOPE,
    ContentRoleAnnotation,
    ContentRoleEvidence,
    SourceLocator,
    TokenPreservationMetadata,
)


class ContentRoleAnnotationContractTest(unittest.TestCase):
    def test_section_annotation_serializes_metadata_only_shadow_contract(self):
        annotation = ContentRoleAnnotation(
            locator=SourceLocator(
                surface="epub_xhtml_body",
                source_path_or_chunk_id="epub:body:copyright-page:1",
                granularity="section",
                structure_hints=("copyright-page", "frontmatter"),
                position_hint="front",
            ),
            role="legal_rights_boilerplate",
            confidence="high",
            evidence=(
                ContentRoleEvidence(
                    signal_family="structural_semantic",
                    strength="strong",
                    metadata_value_kind="epub_type",
                    reason_code="copyright_page_landmark",
                ),
                ContentRoleEvidence(
                    signal_family="body_lexical_cluster",
                    strength="medium",
                    metadata_value_kind="lexical_cluster",
                    reason_code="rights_license_cluster",
                ),
            ),
            reporting_bucket="legal_archive_shadow",
            conflict_notes=("no_reader_visible_conflict",),
        )

        metadata = annotation.to_metadata_dict()

        self.assertEqual(metadata["schema_version"], "content-role-annotation-v1")
        self.assertEqual(
            metadata["allowed_action_envelope"],
            SECTION_BLOCK_ACTION_ENVELOPE,
        )
        self.assertEqual(metadata["role"], "legal_rights_boilerplate")
        self.assertEqual(metadata["confidence"], "high")
        self.assertEqual(metadata["reporting_bucket"], "legal_archive_shadow")
        self.assertFalse(metadata["behavior_allowed"])
        self.assertFalse(metadata["raw_publication_allowed"])
        self.assertEqual(
            set(metadata["risk_approval_flags"]),
            set(BEHAVIOR_RISK_APPROVAL_FLAGS),
        )
        self.assertTrue(
            all(value is False for value in metadata["risk_approval_flags"].values())
        )
        self.assertEqual(len(metadata["evidence"]), 2)
        self.assertNotIn("source_text", str(metadata))
        self.assertNotIn("translated_text", str(metadata))
        self.assertNotIn("prompt", str(metadata).lower())
        self.assertNotIn("provider_request", str(metadata))
        self.assertNotIn("secret", str(metadata).lower())

    def test_token_annotation_serializes_token_scoped_preservation_only(self):
        annotation = ContentRoleAnnotation(
            locator=SourceLocator(
                surface="epub_opf_metadata",
                source_path_or_chunk_id="epub:opf:identifier:isbn",
                granularity="token",
                structure_hints=("identifier",),
                position_hint="metadata",
            ),
            role="publisher_metadata",
            confidence="medium",
            evidence=(
                ContentRoleEvidence(
                    signal_family="structural_semantic",
                    strength="strong",
                    metadata_value_kind="opf_dc_field",
                    reason_code="publisher_identifier_field",
                ),
            ),
            reporting_bucket="token_identifier",
            token_preservation=TokenPreservationMetadata(token_kinds=("isbn",)),
        )

        metadata = annotation.to_metadata_dict()

        self.assertEqual(metadata["allowed_action_envelope"], TOKEN_ACTION_ENVELOPE)
        self.assertEqual(
            metadata["token_preservation"]["token_action_envelope"],
            TOKEN_ACTION_ENVELOPE,
        )
        self.assertTrue(metadata["token_preservation"]["token_scope_only"])
        self.assertFalse(
            metadata["token_preservation"]["section_omit_or_preserve_allowed"]
        )
        self.assertFalse(metadata["behavior_allowed"])
        self.assertFalse(metadata["raw_publication_allowed"])

    def test_empty_evidence_is_rejected_before_serialization(self):
        locator = SourceLocator(
            surface="epub_xhtml_body",
            source_path_or_chunk_id="epub:body:chapter:1",
            granularity="section",
            structure_hints=("chapter",),
            position_hint="body",
        )

        with self.assertRaises(ValueError):
            ContentRoleAnnotation(
                locator=locator,
                role="main_content",
                confidence="medium",
                evidence=(),
                reporting_bucket="main",
            )

    def test_token_envelope_with_section_or_block_granularity_is_rejected(self):
        evidence = (
            ContentRoleEvidence(
                signal_family="structural_semantic",
                strength="strong",
                metadata_value_kind="epub_type",
                reason_code="chapter_body",
            ),
        )

        for granularity in ("section", "block"):
            with self.subTest(granularity=granularity):
                locator = SourceLocator(
                    surface="epub_xhtml_body",
                    source_path_or_chunk_id=f"epub:body:{granularity}:1",
                    granularity=granularity,
                    structure_hints=("chapter",),
                    position_hint="body",
                )

                with self.assertRaises(ValueError):
                    ContentRoleAnnotation(
                        locator=locator,
                        role="main_content",
                        confidence="medium",
                        evidence=evidence,
                        reporting_bucket="main",
                        allowed_action_envelope=TOKEN_ACTION_ENVELOPE,
                    )

    def test_section_block_envelope_with_token_granularity_is_rejected(self):
        locator = SourceLocator(
            surface="epub_opf_metadata",
            source_path_or_chunk_id="epub:opf:identifier:isbn",
            granularity="token",
            structure_hints=("identifier",),
            position_hint="metadata",
        )

        with self.assertRaises(ValueError):
            ContentRoleAnnotation(
                locator=locator,
                role="publisher_metadata",
                confidence="medium",
                evidence=(
                    ContentRoleEvidence(
                        signal_family="structural_semantic",
                        strength="strong",
                        metadata_value_kind="opf_dc_field",
                        reason_code="publisher_identifier_field",
                    ),
                ),
                reporting_bucket="token_identifier",
                allowed_action_envelope=SECTION_BLOCK_ACTION_ENVELOPE,
            )

    def test_high_confidence_requires_multi_signal_evidence(self):
        locator = SourceLocator(
            surface="epub_xhtml_body",
            source_path_or_chunk_id="epub:body:ambiguous:1",
            granularity="block",
            structure_hints=("frontmatter",),
            position_hint="front",
        )
        weak_single_signals = (
            ("provenance_source_clue", "publisher_source_name_alone"),
            ("position_layout", "position_alone"),
            ("path_class_id", "path_alone"),
            ("url_or_rights_pattern", "url_alone"),
            ("position_layout", "all_caps_alone"),
            ("body_lexical_cluster", "one_broad_word"),
        )

        for signal_family, shortcut_code in weak_single_signals:
            with self.subTest(shortcut_code=shortcut_code):
                with self.assertRaises(ValueError):
                    ContentRoleAnnotation(
                        locator=locator,
                        role="legal_rights_boilerplate",
                        confidence="high",
                        evidence=(
                            ContentRoleEvidence(
                                signal_family=signal_family,
                                strength="weak",
                                metadata_value_kind="shortcut",
                                reason_code=shortcut_code,
                            ),
                        ),
                        reporting_bucket="legal_archive_shadow",
                    )

    def test_behavior_changing_action_envelope_is_rejected(self):
        locator = SourceLocator(
            surface="epub_xhtml_body",
            source_path_or_chunk_id="epub:body:chapter:1",
            granularity="section",
            structure_hints=("chapter",),
            position_hint="body",
        )

        with self.assertRaises(ValueError):
            ContentRoleAnnotation(
                locator=locator,
                role="main_content",
                confidence="medium",
                evidence=(
                    ContentRoleEvidence(
                        signal_family="structural_semantic",
                        strength="strong",
                        metadata_value_kind="epub_type",
                        reason_code="chapter_body",
                    ),
                ),
                reporting_bucket="main",
                allowed_action_envelope="omit_section",
            )

    def test_locator_forbidden_scalar_values_raise_before_serialization(self):
        for field_name, kwargs in (
            (
                "source_path_or_chunk_id",
                {"source_path_or_chunk_id": "source_text"},
            ),
            (
                "structure_hints",
                {"structure_hints": ("BEGIN_UNTRUSTED_DOCUMENT_CONTENT",)},
            ),
            ("position_hint", {"position_hint": "translated_text"}),
        ):
            with self.subTest(field_name=field_name):
                source_locator_kwargs = {
                    "surface": "epub_xhtml_body",
                    "source_path_or_chunk_id": "epub:body:chapter:1",
                    "granularity": "section",
                    "structure_hints": ("chapter",),
                    "position_hint": "body",
                }
                source_locator_kwargs.update(kwargs)

                with self.assertRaises(ValueError):
                    SourceLocator(**source_locator_kwargs)

    def test_evidence_forbidden_scalar_values_raise_before_serialization(self):
        for field_name, value in (
            ("metadata_value_kind", "provider_response"),
            ("metadata_value_kind", "prompt"),
            ("reason_code", "RAW PROVIDER body"),
            ("reason_code", "Project Gutenberg excerpt"),
            ("reason_code", "contains secret"),
            ("reason_code", "api key material"),
            ("reason_code", "raw prompt excerpt"),
            ("reason_code", "source excerpt sample"),
            ("reason_code", "translation excerpt sample"),
            ("reason_code", "api-key material"),
            ("reason_code", "apikey material"),
            ("reason_code", "contains-secret"),
            ("reason_code", "secret material"),
            ("reason_code", "prompt excerpt"),
        ):
            with self.subTest(field_name=field_name, value=value):
                evidence_kwargs = {
                    "signal_family": "structural_semantic",
                    "strength": "strong",
                    "metadata_value_kind": "epub_type",
                    "reason_code": "copyright_page_landmark",
                }
                evidence_kwargs[field_name] = value

                with self.assertRaises(ValueError):
                    ContentRoleEvidence(**evidence_kwargs)

    def test_evidence_line_break_scalar_values_raise_before_serialization(self):
        for field_name, value in (
            ("metadata_value_kind", "x\ry"),
            ("reason_code", "safe\r\nreason"),
        ):
            with self.subTest(field_name=field_name, value=repr(value)):
                evidence_kwargs = {
                    "signal_family": "structural_semantic",
                    "strength": "strong",
                    "metadata_value_kind": "epub_type",
                    "reason_code": "copyright_page_landmark",
                }
                evidence_kwargs[field_name] = value

                with self.assertRaises(ValueError):
                    ContentRoleEvidence(**evidence_kwargs)

    def test_reproduction_equivalent_forbidden_provider_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            ContentRoleEvidence(
                signal_family="structural_semantic",
                strength="strong",
                metadata_value_kind="provider_response",
                reason_code="RAW PROVIDER body",
            )

    def test_token_kind_forbidden_scalar_values_raise_before_serialization(self):
        for token_kind in ("raw_translation", "<translation_batch id='1'>", "sk-test"):
            with self.subTest(token_kind=token_kind):
                with self.assertRaises(ValueError):
                    TokenPreservationMetadata(token_kinds=(token_kind,))

    def test_conflict_note_forbidden_scalar_values_raise_before_serialization(self):
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

        for note in (
            "Authorization:" + " Bearer placeholder",
            "owner_policy_tbd_later_behavior",
            "private_diagnostics",
        ):
            with self.subTest(note=note):
                with self.assertRaises(ValueError):
                    ContentRoleAnnotation(
                        locator=locator,
                        role="main_content",
                        confidence="medium",
                        evidence=evidence,
                        reporting_bucket="main",
                        conflict_notes=(note,),
                    )


if __name__ == "__main__":
    unittest.main()
