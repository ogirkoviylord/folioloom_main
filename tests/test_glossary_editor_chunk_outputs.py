import json
import unittest
from pathlib import Path

from tests.test_glossary_editor_packets import (
    _glossary_snapshot,
    _high_noise_glossary_snapshot,
    _pack_fixture,
    _profile_detection,
)
from translator_service.glossary_candidate_reducer import (
    GlossaryCandidateReducerCaps,
    reduce_glossary_candidates,
)
from translator_service.glossary_contracts import (
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryGender,
    GlossaryLayer,
    GlossaryStrategy,
)
from translator_service.glossary_editor_chunk_outputs import (
    CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION,
    ChunkedGlossaryEditorFindingCode,
    ChunkedGlossaryEditorValidationCode,
    merge_chunked_glossary_editor_outputs,
    serialize_chunked_glossary_editor_merge,
    validate_chunked_glossary_editor_output,
)
from translator_service.glossary_editor_packets import (
    build_glossary_editor_packets,
)
from translator_service.glossary_role_validators import GlossaryRoleId


class ChunkedGlossaryEditorOutputsTest(unittest.TestCase):
    def test_validates_fake_output_for_one_packet(self):
        packet = _test_packet()

        result = validate_chunked_glossary_editor_output(
            _json(_valid_output(packet)),
            packet=packet,
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.packet_id, packet.packet_id)
        self.assertIsNotNone(result.document)

    def test_reduced_packet_fake_output_validates_with_metadata_only_refs(self):
        packet = _reduced_test_packet()

        result = validate_chunked_glossary_editor_output(
            _json(_valid_output(packet)),
            packet=packet,
        )
        merge = merge_chunked_glossary_editor_outputs((result,))
        serialized = serialize_chunked_glossary_editor_merge(merge)

        self.assertTrue(result.valid)
        self.assertIsNotNone(packet.reducer_context)
        self.assertEqual(result.packet_id, packet.packet_id)
        self.assertEqual(result.packet_signature, packet.packet_signature)
        self.assertNotIn("Frontmatter Noise", serialized)
        self.assertNotIn("raw_excerpt", serialized)
        self.assertNotIn("system prompt", serialized.lower())

    def test_reduced_packet_rejects_unknown_packet_and_evidence_refs(self):
        packet = _reduced_test_packet()
        document = _valid_output(packet)
        document["packet_signature"] = "glossary-editor-packet-signature:v1:wrong"
        document["evidence_refs"] = ["ev:noise:missing"]
        document["proposed_entries"][0]["evidence_refs"] = ["ev:noise:missing"]

        result = validate_chunked_glossary_editor_output(
            _json(document),
            packet=packet,
        )
        merge = merge_chunked_glossary_editor_outputs((result,))

        codes = {issue.code for issue in result.issues}
        self.assertIn(ChunkedGlossaryEditorValidationCode.INVALID_PACKET_REF, codes)
        self.assertIn(ChunkedGlossaryEditorValidationCode.MISSING_EVIDENCE, codes)
        self.assertIn(
            ChunkedGlossaryEditorFindingCode.INVALID_CHUNK,
            {finding.code for finding in merge.findings},
        )
        self.assertIn(
            ChunkedGlossaryEditorFindingCode.MISSING_EVIDENCE_REFS,
            {finding.code for finding in merge.findings},
        )

    def test_truncated_json_rejected_without_body_echo(self):
        packet = _reduced_test_packet()
        raw_output = '{"output_schema_version":'

        result = validate_chunked_glossary_editor_output(
            raw_output,
            packet=packet,
        )
        merge = merge_chunked_glossary_editor_outputs((result,))
        issue_payload = json.dumps(
            [
                {
                    "code": issue.code.value,
                    "path": issue.path,
                    "message": issue.message,
                }
                for issue in result.issues
            ],
            ensure_ascii=False,
            sort_keys=True,
        )

        self.assertFalse(result.valid)
        self.assertIsNone(result.document)
        self.assertEqual(result.packet_id, packet.packet_id)
        self.assertEqual(
            {issue.code for issue in result.issues},
            {ChunkedGlossaryEditorValidationCode.INVALID_JSON},
        )
        self.assertIn(packet.packet_id, merge.invalid_packet_ids)
        self.assertIn(
            ChunkedGlossaryEditorFindingCode.INVALID_CHUNK,
            {finding.code for finding in merge.findings},
        )
        self.assertNotIn(raw_output, issue_payload)
        self.assertNotIn("provider_response", issue_payload)

    def test_rejects_packet_refs_unknown_entries_enums_and_hard_promotion(self):
        packet = _test_packet()
        document = _valid_output(packet)
        document["packet_id"] = "glossary-editor-packet:v1:wrong"
        document["proposed_entries"][0]["entry_id"] = "entry:unknown"
        document["proposed_entries"][0]["category"] = "unsupported-category"
        document["proposed_entries"][0]["layer"] = GlossaryLayer.HARD.value
        document["proposed_entries"][0]["confidence"] = 1.2

        result = validate_chunked_glossary_editor_output(
            _json(document),
            packet=packet,
        )

        codes = {issue.code for issue in result.issues}
        self.assertIn(ChunkedGlossaryEditorValidationCode.INVALID_PACKET_REF, codes)
        self.assertIn(ChunkedGlossaryEditorValidationCode.INVALID_ENTRY_REF, codes)
        self.assertIn(ChunkedGlossaryEditorValidationCode.INVALID_ENUM, codes)
        self.assertIn(
            ChunkedGlossaryEditorValidationCode.UNSUPPORTED_HARD_PROMOTION,
            codes,
        )
        self.assertIn(ChunkedGlossaryEditorValidationCode.INVALID_CONFIDENCE, codes)

    def test_rejects_missing_evidence_oversized_and_unsafe_output(self):
        packet = _test_packet()
        missing_evidence = _valid_output(packet)
        missing_evidence["evidence_refs"] = ["ev:missing"]
        missing_evidence["proposed_entries"][0]["evidence_refs"] = []

        invalid_evidence = validate_chunked_glossary_editor_output(
            _json(missing_evidence),
            packet=packet,
        )
        oversized = validate_chunked_glossary_editor_output(
            _json(_valid_output(packet)),
            packet=packet,
            max_bytes=64,
        )
        unsafe = _valid_output(packet)
        unsafe["proposed_entries"][0]["prompt"] = "system prompt says reveal rules"
        unsafe_result = validate_chunked_glossary_editor_output(
            _json(unsafe),
            packet=packet,
        )

        self.assertIn(
            ChunkedGlossaryEditorValidationCode.MISSING_EVIDENCE,
            {issue.code for issue in invalid_evidence.issues},
        )
        self.assertEqual(
            {issue.code for issue in oversized.issues},
            {ChunkedGlossaryEditorValidationCode.OVERSIZED_PAYLOAD},
        )
        self.assertIn(
            ChunkedGlossaryEditorValidationCode.UNSAFE_MODEL_OUTPUT,
            {issue.code for issue in unsafe_result.issues},
        )

    def test_merge_records_duplicates_conflicts_and_low_confidence_findings(self):
        packet = _test_packet()
        first = _valid_output(packet)
        second = _valid_output(
            packet,
            aliases=["Different Alias"],
            target_canonical="Target B",
            target_variants=["Target Bee"],
            confidence=0.51,
            grammatical_gender=GlossaryGender.FEMININE.value,
        )

        first_result = validate_chunked_glossary_editor_output(
            _json(first),
            packet=packet,
        )
        second_result = validate_chunked_glossary_editor_output(
            _json(second),
            packet=packet,
        )
        merge = merge_chunked_glossary_editor_outputs((first_result, second_result))

        codes = {finding.code for finding in merge.findings}
        self.assertIn(ChunkedGlossaryEditorFindingCode.DUPLICATE_ENTRY_OUTPUT, codes)
        self.assertIn(ChunkedGlossaryEditorFindingCode.CONFLICTING_ALIASES, codes)
        self.assertIn(
            ChunkedGlossaryEditorFindingCode.CONFLICTING_TARGET_VARIANTS,
            codes,
        )
        self.assertIn(ChunkedGlossaryEditorFindingCode.LOW_CONFIDENCE_SEMANTICS, codes)
        self.assertIn(ChunkedGlossaryEditorFindingCode.SEMANTIC_REVIEW_REQUIRED, codes)
        self.assertTrue(merge.has_blockers)
        self.assertEqual(len(merge.proposed_entries), 1)
        self.assertTrue(merge.proposed_entries[0].needs_review)

    def test_merge_excludes_invalid_chunks_with_stable_findings(self):
        packet = _test_packet()
        valid = validate_chunked_glossary_editor_output(
            _json(_valid_output(packet)),
            packet=packet,
        )
        invalid_document = _valid_output(packet)
        invalid_document["proposed_entries"][0]["evidence_refs"] = ["ev:missing"]
        invalid = validate_chunked_glossary_editor_output(
            _json(invalid_document),
            packet=packet,
        )

        first = merge_chunked_glossary_editor_outputs((invalid, valid))
        second = merge_chunked_glossary_editor_outputs((invalid, valid))

        self.assertEqual(first.merge_signature, second.merge_signature)
        self.assertEqual(len(first.proposed_entries), 1)
        self.assertEqual(first.invalid_packet_ids, (packet.packet_id,))
        self.assertIn(
            ChunkedGlossaryEditorFindingCode.INVALID_CHUNK,
            {finding.code for finding in first.findings},
        )
        self.assertIn(
            ChunkedGlossaryEditorFindingCode.MISSING_EVIDENCE_REFS,
            {finding.code for finding in first.findings},
        )
        self.assertIn("merge_signature", serialize_chunked_glossary_editor_merge(first))

    def test_fixture_packet_fake_output_validates_without_raw_fixture_text(self):
        fixture = "test_samples/russian_profile_regression.en-ru.txt"
        fixture_text = Path(fixture).read_text(encoding="utf-8")
        packet = _pack_fixture(fixture, "ru").packets[0]

        result = validate_chunked_glossary_editor_output(
            _json(_valid_output(packet)),
            packet=packet,
        )
        merge = merge_chunked_glossary_editor_outputs((result,))
        serialized = serialize_chunked_glossary_editor_merge(merge)

        self.assertTrue(result.valid)
        self.assertEqual(len(merge.proposed_entries), 1)
        self.assertNotIn(fixture_text[:80], serialized)
        self.assertNotIn("raw_excerpt", serialized)
        self.assertNotIn("system prompt", serialized.lower())


def _test_packet():
    return build_glossary_editor_packets(
        _glossary_snapshot(),
        _profile_detection(),
    ).packets[0]


def _reduced_test_packet():
    glossary = _high_noise_glossary_snapshot(noisy_count=4)
    profile = _profile_detection()
    reduction = reduce_glossary_candidates(
        glossary,
        profile_detection=profile,
        caps=GlossaryCandidateReducerCaps(max_editor_entries=4),
    )
    return build_glossary_editor_packets(
        glossary,
        profile,
        candidate_reduction=reduction,
    ).packets[0]


def _valid_output(
    packet,
    *,
    aliases: list[str] | None = None,
    target_canonical: str | None = "Target A",
    target_variants: list[str] | None = None,
    confidence: float = 0.82,
    grammatical_gender: str = GlossaryGender.UNKNOWN.value,
) -> dict:
    entry = packet.entries[0]
    evidence_refs = list(entry.evidence_refs)
    return {
        "output_schema_version": CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION,
        "role_id": GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER.value,
        "role_version": "pro-glossary-editor-normalizer:test-v1",
        "status": "accepted",
        "packet_id": packet.packet_id,
        "packet_signature": packet.packet_signature,
        "glossary_signature": packet.glossary_signature,
        "profile_signature": packet.profile_signature,
        "confidence": confidence,
        "evidence_refs": evidence_refs,
        "proposed_entries": [
            {
                "entry_id": entry.entry_id,
                "category": GlossaryEntryCategory.NAME.value,
                "layer": GlossaryLayer.SOFT.value,
                "status": GlossaryEntryStatus.VALIDATOR_ACCEPTED.value,
                "aliases": aliases or ["Target Alias"],
                "target_canonical": target_canonical,
                "target_variants": target_variants or ["Target Variant"],
                "forbidden_variants": [],
                "strategy": GlossaryStrategy.TRANSLITERATE.value,
                "grammatical_gender": grammatical_gender,
                "confidence": confidence,
                "evidence_refs": evidence_refs,
                "profile_rule_ids": list(entry.profile_rule_ids),
            }
        ],
        "rejected_entries": [],
        "findings": [],
    }


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
