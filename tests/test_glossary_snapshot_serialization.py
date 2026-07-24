import hashlib
import json
import unittest
from dataclasses import replace

from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryEvidenceType,
    GlossaryGender,
    GlossaryLayer,
    GlossarySnapshot,
    GlossaryStrategy,
    glossary_snapshot_signature,
)
from translator_service.glossary_snapshot_serialization import (
    GlossarySnapshotSerializationError,
    GlossarySnapshotSerializationErrorCode,
    deserialize_glossary_snapshot_v1,
    serialize_glossary_snapshot_v1,
    snapshot_payload_sha256,
)


class GlossarySnapshotSerializationTest(unittest.TestCase):
    def test_round_trip_preserves_fields_and_distinguishes_payload_hash(self):
        snapshot = GlossarySnapshot(
            snapshot_id="snapshot-1",
            source_language="en",
            target_language="ru",
            schema_version="glossary-snapshot-v1",
            policy_version="glossary-policy-v9",
            profile_signature="book-profile:abc",
            evidence=(
                GlossaryEvidenceRef(
                    evidence_id="ev-b",
                    evidence_type=GlossaryEvidenceType.TITLE,
                    unit_sequence=2,
                    source_block_id="block-2",
                    source_scope="chapter-2",
                    surface=GlossaryEvidenceSurface.HEADING,
                    occurrence_count=3,
                    offset_bucket="20-29",
                ),
                GlossaryEvidenceRef(
                    evidence_id="ev-a",
                    evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
                    unit_sequence=1,
                    source_block_id="block-1",
                    source_scope="chapter-1",
                    surface=GlossaryEvidenceSurface.BODY,
                    occurrence_count=1,
                    offset_bucket="0-9",
                ),
            ),
            entries=(
                GlossaryEntry(
                    entry_id="entry-b",
                    category=GlossaryEntryCategory.TERM,
                    layer=GlossaryLayer.HARD,
                    status=GlossaryEntryStatus.OWNER_PINNED,
                    source_canonical="Zulu",
                    aliases=("zeta", "alpha"),
                    target_canonical="Зулу",
                    target_variants=("зулу", "Зулу"),
                    forbidden_variants=("Зулус", "Зулы"),
                    evidence_refs=("ev-b", "ev-a"),
                    confidence=1.0,
                    strategy=GlossaryStrategy.TRANSLITERATE,
                    grammatical_gender=GlossaryGender.MASCULINE,
                    morphology_notes=("plural=zulu", "case=genitive"),
                    profile_rule_ids=("rule-b", "rule-a"),
                ),
                GlossaryEntry(
                    entry_id="entry-a",
                    category=GlossaryEntryCategory.NAME,
                    layer=GlossaryLayer.SOFT,
                    status=GlossaryEntryStatus.AUTO_DETECTED,
                    source_canonical="Alpha",
                    evidence_refs=("ev-a",),
                    confidence=0.5,
                ),
            ),
        )

        payload = serialize_glossary_snapshot_v1(snapshot)
        decoded = deserialize_glossary_snapshot_v1(payload)

        self.assertEqual(decoded.entries[0].entry_id, "entry-a")
        self.assertEqual(decoded.entries[1].entry_id, "entry-b")
        self.assertEqual(decoded.evidence[0].evidence_id, "ev-a")
        self.assertEqual(decoded.evidence[1].evidence_id, "ev-b")
        self.assertEqual(decoded.entries[1].aliases, ("alpha", "zeta"))
        self.assertEqual(decoded.entries[1].evidence_refs, ("ev-a", "ev-b"))
        self.assertEqual(decoded.entries[1].profile_rule_ids, ("rule-a", "rule-b"))
        self.assertEqual(payload, serialize_glossary_snapshot_v1(decoded))
        self.assertEqual(
            snapshot_payload_sha256(payload), hashlib.sha256(payload).hexdigest()
        )
        self.assertNotEqual(
            snapshot_payload_sha256(payload), glossary_snapshot_signature(decoded)
        )

    def test_serialization_matches_literal_canonical_utf8_payload(self):
        snapshot = _valid_snapshot()
        entry_b = snapshot.entries[0]
        snapshot = replace(
            snapshot,
            entries=(
                replace(
                    entry_b,
                    aliases=("zeta", "alpha"),
                    evidence_refs=("ev-b", "ev-a"),
                    target_canonical="Зулу",
                    target_variants=("зулу", "Зулу"),
                    forbidden_variants=("Зулус", "Зулы"),
                    morphology_notes=("plural=zulu", "case=genitive"),
                    profile_rule_ids=("rule-b", "rule-a"),
                ),
                snapshot.entries[1],
            ),
        )

        expected_payload = bytes(
            (
            '{"entries":[{"aliases":[],"category":"term","confidence":0.5,'
            '"entry_id":"entry-a","evidence_refs":["ev-a"],'
            '"forbidden_variants":[],"grammatical_gender":"unknown",'
            '"layer":"soft","morphology_notes":[],"profile_rule_ids":[],'
            '"schema_version":"glossary-entry-v1","source_canonical":"Alpha",'
            '"status":"auto_detected","strategy":"unknown",'
            '"target_canonical":null,"target_variants":[]},{"aliases":["alpha",'
            '"zeta"],"category":"term","confidence":0.5,"entry_id":"entry-b",'
            '"evidence_refs":["ev-a","ev-b"],"forbidden_variants":["Зулус",'
            '"Зулы"],"grammatical_gender":"unknown","layer":"soft",'
            '"morphology_notes":["case=genitive","plural=zulu"],'
            '"profile_rule_ids":["rule-a","rule-b"],'
            '"schema_version":"glossary-entry-v1","source_canonical":"Beta",'
            '"status":"auto_detected","strategy":"unknown",'
            '"target_canonical":"Зулу","target_variants":["Зулу","зулу"]}],'
            '"evidence":[{"evidence_id":"ev-a","evidence_type":"source_anchor",'
            '"occurrence_count":1,"offset_bucket":"unknown","raw_excerpt":null,'
            '"source_block_id":"block-1","source_scope":"chapter-1",'
            '"surface":"body","unit_sequence":1},{"evidence_id":"ev-b",'
            '"evidence_type":"source_anchor","occurrence_count":1,'
            '"offset_bucket":"unknown","raw_excerpt":null,'
            '"source_block_id":"block-2","source_scope":"chapter-2",'
            '"surface":"body","unit_sequence":2}],'
            '"policy_version":"glossary-policy-v1",'
            '"profile_signature":"book-profile:none",'
            '"schema_version":"glossary-snapshot-v1","snapshot_id":"snapshot-1",'
                '"source_language":"en","target_language":"ru"}'
            ),
            "utf-8",
        )

        self.assertEqual(serialize_glossary_snapshot_v1(snapshot), expected_payload)

    def test_deserialization_rejects_missing_unknown_invalid_and_raw_excerpt_payloads(
        self,
    ):
        payload = serialize_glossary_snapshot_v1(_valid_snapshot())
        decoded = json.loads(payload)
        cases = []

        missing = dict(decoded)
        del missing["snapshot_id"]
        cases.append(missing)

        unknown = dict(decoded)
        unknown["unexpected"] = "value"
        cases.append(unknown)

        invalid_enum = json.loads(payload)
        invalid_enum["entries"][0]["category"] = "unsupported"
        cases.append(invalid_enum)

        raw_excerpt = json.loads(payload)
        raw_excerpt["evidence"][0]["raw_excerpt"] = "must not persist"
        cases.append(raw_excerpt)

        for invalid_payload in cases:
            with self.subTest(invalid_payload=invalid_payload):
                with self.assertRaises(GlossarySnapshotSerializationError) as raised:
                    deserialize_glossary_snapshot_v1(
                        json.dumps(
                            invalid_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                self.assertEqual(
                    raised.exception.code,
                    GlossarySnapshotSerializationErrorCode.INVALID_PAYLOAD,
                )

    def test_deserialization_rejects_noncanonical_payload(self):
        payload = serialize_glossary_snapshot_v1(_valid_snapshot())
        decoded = json.loads(payload)
        decoded["entries"] = list(reversed(decoded["entries"]))
        noncanonical_payload = json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        with self.assertRaises(GlossarySnapshotSerializationError) as raised:
            deserialize_glossary_snapshot_v1(noncanonical_payload)

        self.assertEqual(
            raised.exception.code,
            GlossarySnapshotSerializationErrorCode.NONCANONICAL_PAYLOAD,
        )

    def test_deserialization_rejects_unknown_snapshot_and_entry_fields(self):
        payload = serialize_glossary_snapshot_v1(_valid_snapshot())
        decoded = json.loads(payload)
        unknown_snapshot_field = dict(decoded, unexpected="value")
        unknown_entry_field = json.loads(payload)
        unknown_entry_field["entries"][0]["unexpected"] = "value"

        for invalid_payload in (unknown_snapshot_field, unknown_entry_field):
            with self.subTest(invalid_payload=invalid_payload):
                with self.assertRaises(GlossarySnapshotSerializationError) as raised:
                    deserialize_glossary_snapshot_v1(_canonical_json_bytes(invalid_payload))
                self.assertEqual(
                    raised.exception.code,
                    GlossarySnapshotSerializationErrorCode.INVALID_PAYLOAD,
                )

    def test_deserialization_rejects_unsupported_snapshot_and_entry_schemas(self):
        payload = serialize_glossary_snapshot_v1(_valid_snapshot())
        decoded = json.loads(payload)
        unsupported_snapshot_schema = dict(decoded, schema_version="unsupported")
        unsupported_entry_schema = json.loads(payload)
        unsupported_entry_schema["entries"][0]["schema_version"] = "unsupported"

        for invalid_payload in (unsupported_snapshot_schema, unsupported_entry_schema):
            with self.subTest(invalid_payload=invalid_payload):
                with self.assertRaises(GlossarySnapshotSerializationError) as raised:
                    deserialize_glossary_snapshot_v1(_canonical_json_bytes(invalid_payload))
                self.assertEqual(
                    raised.exception.code,
                    GlossarySnapshotSerializationErrorCode.UNSUPPORTED_SCHEMA,
                )

    def test_serialization_rejects_invalid_snapshot_and_raw_excerpt(self):
        valid_snapshot = _valid_snapshot()
        invalid_snapshot = replace(valid_snapshot, schema_version="unsupported")
        raw_excerpt_snapshot = replace(
            valid_snapshot,
            evidence=(replace(valid_snapshot.evidence[0], raw_excerpt="not allowed"),),
        )

        for snapshot in (invalid_snapshot, raw_excerpt_snapshot):
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(GlossarySnapshotSerializationError) as raised:
                    serialize_glossary_snapshot_v1(snapshot)
                self.assertEqual(
                    raised.exception.code,
                    GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT,
                )

    def test_serialization_rejects_malformed_snapshot_collections(self):
        snapshot = _valid_snapshot()
        malformed_snapshots = (
            replace(snapshot, entries=None),
            replace(snapshot, evidence=None),
            replace(snapshot, entries=[snapshot.entries[0]]),
            replace(snapshot, evidence=[snapshot.evidence[0]]),
            replace(snapshot, entries=("not-an-entry",)),
            replace(snapshot, evidence=("not-an-evidence",)),
        )

        for malformed_snapshot in malformed_snapshots:
            with self.subTest(malformed_snapshot=malformed_snapshot):
                with self.assertRaises(GlossarySnapshotSerializationError) as raised:
                    serialize_glossary_snapshot_v1(malformed_snapshot)
                self.assertEqual(
                    raised.exception.code,
                    GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT,
                )


def _valid_snapshot() -> GlossarySnapshot:
    return GlossarySnapshot(
        snapshot_id="snapshot-1",
        source_language="en",
        target_language="ru",
        evidence=(
            GlossaryEvidenceRef(
                evidence_id="ev-b",
                evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
                unit_sequence=2,
                source_block_id="block-2",
                source_scope="chapter-2",
                surface=GlossaryEvidenceSurface.BODY,
            ),
            GlossaryEvidenceRef(
                evidence_id="ev-a",
                evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
                unit_sequence=1,
                source_block_id="block-1",
                source_scope="chapter-1",
                surface=GlossaryEvidenceSurface.BODY,
            ),
        ),
        entries=(
            GlossaryEntry(
                entry_id="entry-b",
                category=GlossaryEntryCategory.TERM,
                layer=GlossaryLayer.SOFT,
                status=GlossaryEntryStatus.AUTO_DETECTED,
                source_canonical="Beta",
                evidence_refs=("ev-b",),
                confidence=0.5,
            ),
            GlossaryEntry(
                entry_id="entry-a",
                category=GlossaryEntryCategory.TERM,
                layer=GlossaryLayer.SOFT,
                status=GlossaryEntryStatus.AUTO_DETECTED,
                source_canonical="Alpha",
                evidence_refs=("ev-a",),
                confidence=0.5,
            ),
        ),
    )


def _canonical_json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
