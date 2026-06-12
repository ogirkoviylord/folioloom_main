import json
import tempfile
import unittest
from pathlib import Path

from translator_service.glossary_profile_diagnostics import (
    GLOSSARY_PROFILE_DIAGNOSTIC_FILENAME,
    GlossaryProfileDiagnosticValidationCode,
    RawFieldClassification,
    RawFieldManifestEntry,
    build_glossary_profile_diagnostic_sidecar,
    glossary_profile_diagnostic_metadata_summary,
    read_glossary_profile_diagnostic_sidecar,
    validate_glossary_profile_diagnostic_sidecar,
    write_glossary_profile_diagnostic_sidecar,
)
from translator_service.security_telemetry import sanitize_security_payload


class GlossaryProfileDiagnosticsTest(unittest.TestCase):
    def test_accepts_compact_sidecar_and_round_trips_dedicated_file(self):
        sidecar = build_glossary_profile_diagnostic_sidecar(
            run_or_fixture_ref="fixture:sample-book",
            source_language="en",
            target_language="ru",
            translation_mode="book",
            translation_snapshot_ref="snapshot:v1:abc",
            glossary_signature="glossary:v1:def",
            profile_signature="profile:v1:ghi",
            sections={
                "candidate_records": [
                    {
                        "candidate_id": "candidate-1",
                        "entry_id": "entry-1",
                        "category": "name",
                        "layer": "soft",
                        "status": "uncertain",
                        "confidence": 0.61,
                        "evidence_refs": ["evidence-1"],
                    }
                ],
                "validation_failures": [],
            },
            created_at="2026-06-12T10:00:00+00:00",
        )

        result = validate_glossary_profile_diagnostic_sidecar(sidecar)

        self.assertTrue(result.valid, result.issues)
        self.assertEqual(
            sidecar["access_boundary"]["admin_boundary"],
            "ssh_tunneled_admin_session_required",
        )
        self.assertFalse(sidecar["access_boundary"]["ordinary_logs_allowed"])
        self.assertEqual(sidecar["retention_policy"], "TBD")
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / GLOSSARY_PROFILE_DIAGNOSTIC_FILENAME
            write_glossary_profile_diagnostic_sidecar(path, sidecar)
            self.assertEqual(read_glossary_profile_diagnostic_sidecar(path), sidecar)
            with self.assertRaisesRegex(
                ValueError,
                GLOSSARY_PROFILE_DIAGNOSTIC_FILENAME,
            ):
                write_glossary_profile_diagnostic_sidecar(
                    Path(tempdir) / "run.json",
                    sidecar,
                )

    def test_raw_capable_fields_require_manifest_entries(self):
        raw_text = "Sensitive source excerpt around a candidate."
        sidecar = build_glossary_profile_diagnostic_sidecar(
            run_or_fixture_ref="fixture:raw",
            sections={
                "candidate_records": [
                    {
                        "candidate_id": "candidate-raw",
                        "raw_candidate_text": raw_text,
                    }
                ]
            },
            created_at="2026-06-12T10:00:00+00:00",
        )

        missing = validate_glossary_profile_diagnostic_sidecar(sidecar)

        self.assertFalse(missing.valid)
        self.assertIn(
            GlossaryProfileDiagnosticValidationCode.MISSING_RAW_FIELD_MANIFEST_ENTRY,
            {issue.code for issue in missing.issues},
        )

        sidecar["raw_text_field_manifest"] = [
            RawFieldManifestEntry(
                path="sections.candidate_records[].raw_candidate_text",
                classification=RawFieldClassification.NEAR_RAW_CANDIDATE_TEXT,
                source="deterministic_candidate_scanner",
            ).to_payload()
        ]
        valid = validate_glossary_profile_diagnostic_sidecar(sidecar)
        summary = glossary_profile_diagnostic_metadata_summary(sidecar)
        serialized_summary = json.dumps(summary, ensure_ascii=False, sort_keys=True)

        self.assertTrue(valid.valid, valid.issues)
        self.assertNotIn(raw_text, serialized_summary)
        self.assertNotIn("sections.candidate_records", serialized_summary)
        self.assertNotIn(raw_text, json.dumps(sanitize_security_payload(summary)))

    def test_rejects_secret_material_inside_raw_provider_payloads(self):
        auth_header = "Bearer " + "testsecret123456"
        sidecar = build_glossary_profile_diagnostic_sidecar(
            run_or_fixture_ref="fixture:provider",
            raw_text_field_manifest=[
                RawFieldManifestEntry(
                    path="sections.role_traces[].raw_provider_request_body",
                    classification=RawFieldClassification.PROVIDER_REQUEST_BODY,
                    source="provider_role_trace",
                )
            ],
            sections={
                "role_traces": [
                    {
                        "role_id": "pro_glossary_editor_normalizer",
                        "raw_provider_request_body": {
                            "headers": {
                                "provider_auth": auth_header,
                            }
                        },
                    }
                ]
            },
            created_at="2026-06-12T10:00:00+00:00",
        )

        result = validate_glossary_profile_diagnostic_sidecar(sidecar)

        self.assertFalse(result.valid)
        self.assertIn(
            GlossaryProfileDiagnosticValidationCode.SECRET_MATERIAL,
            {issue.code for issue in result.issues},
        )

    def test_rejects_ordinary_surface_and_non_tbd_policy(self):
        sidecar = build_glossary_profile_diagnostic_sidecar(
            run_or_fixture_ref="fixture:policy",
            created_at="2026-06-12T10:00:00+00:00",
        )
        sidecar["access_boundary"]["telemetry_allowed"] = True
        sidecar["retention_policy"] = "owner_decision_pending"

        result = validate_glossary_profile_diagnostic_sidecar(sidecar)
        issues = {(issue.code, issue.path) for issue in result.issues}

        self.assertFalse(result.valid)
        self.assertIn(
            (
                GlossaryProfileDiagnosticValidationCode.INVALID_ACCESS_BOUNDARY,
                "access_boundary.telemetry_allowed",
            ),
            issues,
        )
        self.assertIn(
            (
                GlossaryProfileDiagnosticValidationCode.INVALID_POLICY,
                "retention_policy",
            ),
            issues,
        )


if __name__ == "__main__":
    unittest.main()
