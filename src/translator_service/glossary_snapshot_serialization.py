from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn

from translator_service.glossary_contracts import (
    GLOSSARY_ENTRY_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
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
    validate_glossary_snapshot,
)

GLOSSARY_SNAPSHOT_SERIALIZATION_VERSION = "glossary-snapshot-serialization-v1"


class GlossarySnapshotSerializationErrorCode(StrEnum):
    INVALID_SNAPSHOT = "invalid_snapshot"
    INVALID_PAYLOAD = "invalid_payload"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    NONCANONICAL_PAYLOAD = "noncanonical_payload"


@dataclass(frozen=True)
class GlossarySnapshotSerializationError(ValueError):
    code: GlossarySnapshotSerializationErrorCode
    message: str

    def __str__(self) -> str:
        return self.message


def serialize_glossary_snapshot_v1(snapshot: GlossarySnapshot) -> bytes:
    """Return the field-preserving canonical v1 custody payload for a snapshot."""
    _validate_snapshot(snapshot)
    return _encode_canonical(_snapshot_to_payload(snapshot))


def deserialize_glossary_snapshot_v1(payload: bytes) -> GlossarySnapshot:
    """Decode only a canonical, field-complete, raw-excerpt-free v1 payload."""
    if not isinstance(payload, bytes):
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_PAYLOAD,
            "payload must be bytes",
        )

    try:
        decoded = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _PayloadDecodeError) as error:
        _raise(GlossarySnapshotSerializationErrorCode.INVALID_PAYLOAD, str(error))

    try:
        snapshot = _snapshot_from_payload(decoded)
    except _PayloadDecodeError as error:
        _raise(GlossarySnapshotSerializationErrorCode.INVALID_PAYLOAD, str(error))
    _validate_snapshot(snapshot)
    canonical_payload = serialize_glossary_snapshot_v1(snapshot)
    if canonical_payload != payload:
        _raise(
            GlossarySnapshotSerializationErrorCode.NONCANONICAL_PAYLOAD,
            "payload is not canonical glossary snapshot serialization v1",
        )
    return snapshot


def snapshot_payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes):
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_PAYLOAD,
            "payload must be bytes",
        )
    return hashlib.sha256(payload).hexdigest()


def _validate_snapshot(snapshot: GlossarySnapshot) -> None:
    if not isinstance(snapshot, GlossarySnapshot):
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT,
            "snapshot must be a GlossarySnapshot",
        )
    _validate_snapshot_collections(snapshot)
    result = validate_glossary_snapshot(snapshot, allow_raw_diagnostics=False)
    if not result.valid:
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT,
            "; ".join(f"{issue.path}: {issue.message}" for issue in result.issues),
        )
    try:
        _snapshot_to_payload(snapshot)
    except _PayloadDecodeError as error:
        _raise(GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT, str(error))


def _validate_snapshot_collections(snapshot: GlossarySnapshot) -> None:
    if not isinstance(snapshot.entries, tuple):
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT,
            "entries must be a tuple",
        )
    if not all(isinstance(entry, GlossaryEntry) for entry in snapshot.entries):
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT,
            "entries must contain GlossaryEntry values",
        )
    if not isinstance(snapshot.evidence, tuple):
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT,
            "evidence must be a tuple",
        )
    if not all(
        isinstance(evidence, GlossaryEvidenceRef) for evidence in snapshot.evidence
    ):
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_SNAPSHOT,
            "evidence must contain GlossaryEvidenceRef values",
        )


def _snapshot_to_payload(snapshot: GlossarySnapshot) -> dict[str, Any]:
    return {
        "entries": [
            _entry_to_payload(entry)
            for entry in sorted(snapshot.entries, key=lambda entry: entry.entry_id)
        ],
        "evidence": [
            _evidence_to_payload(evidence)
            for evidence in sorted(
                snapshot.evidence, key=lambda evidence: evidence.evidence_id
            )
        ],
        "policy_version": _required_text(snapshot.policy_version, "policy_version"),
        "profile_signature": _required_text(
            snapshot.profile_signature, "profile_signature"
        ),
        "schema_version": _required_text(snapshot.schema_version, "schema_version"),
        "snapshot_id": _required_text(snapshot.snapshot_id, "snapshot_id"),
        "source_language": _required_text(snapshot.source_language, "source_language"),
        "target_language": _required_text(snapshot.target_language, "target_language"),
    }


def _entry_to_payload(entry: GlossaryEntry) -> dict[str, Any]:
    if not isinstance(entry, GlossaryEntry):
        raise _PayloadDecodeError("entries must contain GlossaryEntry values")
    return {
        "aliases": _canonical_texts(entry.aliases, "aliases"),
        "category": _enum_value(entry.category, GlossaryEntryCategory, "category"),
        "confidence": _confidence(entry.confidence),
        "entry_id": _required_text(entry.entry_id, "entry_id"),
        "evidence_refs": _canonical_texts(entry.evidence_refs, "evidence_refs"),
        "forbidden_variants": _canonical_texts(
            entry.forbidden_variants, "forbidden_variants"
        ),
        "grammatical_gender": _enum_value(
            entry.grammatical_gender,
            GlossaryGender,
            "grammatical_gender",
        ),
        "layer": _enum_value(entry.layer, GlossaryLayer, "layer"),
        "morphology_notes": _canonical_texts(
            entry.morphology_notes, "morphology_notes"
        ),
        "profile_rule_ids": _canonical_texts(
            entry.profile_rule_ids, "profile_rule_ids"
        ),
        "schema_version": _required_text(entry.schema_version, "schema_version"),
        "source_canonical": _required_text(entry.source_canonical, "source_canonical"),
        "status": _enum_value(entry.status, GlossaryEntryStatus, "status"),
        "strategy": _enum_value(entry.strategy, GlossaryStrategy, "strategy"),
        "target_canonical": _optional_text(entry.target_canonical, "target_canonical"),
        "target_variants": _canonical_texts(entry.target_variants, "target_variants"),
    }


def _evidence_to_payload(evidence: GlossaryEvidenceRef) -> dict[str, Any]:
    if not isinstance(evidence, GlossaryEvidenceRef):
        raise _PayloadDecodeError("evidence must contain GlossaryEvidenceRef values")
    if evidence.raw_excerpt is not None:
        raise _PayloadDecodeError("raw_excerpt is not allowed")
    return {
        "evidence_id": _required_text(evidence.evidence_id, "evidence_id"),
        "evidence_type": _enum_value(
            evidence.evidence_type, GlossaryEvidenceType, "evidence_type"
        ),
        "occurrence_count": _positive_int(
            evidence.occurrence_count, "occurrence_count"
        ),
        "offset_bucket": _required_text(evidence.offset_bucket, "offset_bucket"),
        "raw_excerpt": None,
        "source_block_id": _required_text(evidence.source_block_id, "source_block_id"),
        "source_scope": _required_text(evidence.source_scope, "source_scope"),
        "surface": _enum_value(evidence.surface, GlossaryEvidenceSurface, "surface"),
        "unit_sequence": _non_negative_int(evidence.unit_sequence, "unit_sequence"),
    }


def _snapshot_from_payload(payload: Any) -> GlossarySnapshot:
    mapping = _object_with_exact_fields(payload, _SNAPSHOT_FIELDS, "snapshot")
    schema_version = _required_text(mapping["schema_version"], "schema_version")
    if schema_version != GLOSSARY_SNAPSHOT_SCHEMA_VERSION:
        _raise(
            GlossarySnapshotSerializationErrorCode.UNSUPPORTED_SCHEMA,
            "unsupported snapshot schema_version",
        )
    return GlossarySnapshot(
        snapshot_id=_required_text(mapping["snapshot_id"], "snapshot_id"),
        source_language=_required_text(mapping["source_language"], "source_language"),
        target_language=_required_text(mapping["target_language"], "target_language"),
        entries=tuple(
            _entry_from_payload(item)
            for item in _list(mapping["entries"], "entries")
        ),
        evidence=tuple(
            _evidence_from_payload(item)
            for item in _list(mapping["evidence"], "evidence")
        ),
        schema_version=schema_version,
        policy_version=_required_text(mapping["policy_version"], "policy_version"),
        profile_signature=_required_text(
            mapping["profile_signature"], "profile_signature"
        ),
    )


def _entry_from_payload(payload: Any) -> GlossaryEntry:
    mapping = _object_with_exact_fields(payload, _ENTRY_FIELDS, "entry")
    schema_version = _required_text(mapping["schema_version"], "entry.schema_version")
    if schema_version != GLOSSARY_ENTRY_SCHEMA_VERSION:
        _raise(
            GlossarySnapshotSerializationErrorCode.UNSUPPORTED_SCHEMA,
            "unsupported entry schema_version",
        )
    return GlossaryEntry(
        entry_id=_required_text(mapping["entry_id"], "entry_id"),
        category=_enum(mapping["category"], GlossaryEntryCategory, "category"),
        layer=_enum(mapping["layer"], GlossaryLayer, "layer"),
        status=_enum(mapping["status"], GlossaryEntryStatus, "status"),
        source_canonical=_required_text(
            mapping["source_canonical"], "source_canonical"
        ),
        evidence_refs=_text_tuple(mapping["evidence_refs"], "evidence_refs"),
        confidence=_confidence(mapping["confidence"]),
        schema_version=schema_version,
        aliases=_text_tuple(mapping["aliases"], "aliases"),
        target_canonical=_optional_text(
            mapping["target_canonical"], "target_canonical"
        ),
        target_variants=_text_tuple(mapping["target_variants"], "target_variants"),
        forbidden_variants=_text_tuple(
            mapping["forbidden_variants"], "forbidden_variants"
        ),
        strategy=_enum(mapping["strategy"], GlossaryStrategy, "strategy"),
        grammatical_gender=_enum(
            mapping["grammatical_gender"], GlossaryGender, "grammatical_gender"
        ),
        morphology_notes=_text_tuple(mapping["morphology_notes"], "morphology_notes"),
        profile_rule_ids=_text_tuple(mapping["profile_rule_ids"], "profile_rule_ids"),
    )


def _evidence_from_payload(payload: Any) -> GlossaryEvidenceRef:
    mapping = _object_with_exact_fields(payload, _EVIDENCE_FIELDS, "evidence")
    if mapping["raw_excerpt"] is not None:
        _raise(
            GlossarySnapshotSerializationErrorCode.INVALID_PAYLOAD,
            "raw_excerpt is not allowed",
        )
    return GlossaryEvidenceRef(
        evidence_id=_required_text(mapping["evidence_id"], "evidence_id"),
        evidence_type=_enum(
            mapping["evidence_type"], GlossaryEvidenceType, "evidence_type"
        ),
        unit_sequence=_non_negative_int(mapping["unit_sequence"], "unit_sequence"),
        source_block_id=_required_text(mapping["source_block_id"], "source_block_id"),
        source_scope=_required_text(mapping["source_scope"], "source_scope"),
        surface=_enum(mapping["surface"], GlossaryEvidenceSurface, "surface"),
        occurrence_count=_positive_int(mapping["occurrence_count"], "occurrence_count"),
        offset_bucket=_required_text(mapping["offset_bucket"], "offset_bucket"),
        raw_excerpt=None,
    )


def _encode_canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _object_with_exact_fields(
    payload: Any, fields: frozenset[str], name: str
) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != fields:
        raise _PayloadDecodeError(f"{name} fields are missing or unknown")
    return payload


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise _PayloadDecodeError(f"{name} must be a list")
    return value


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _PayloadDecodeError(f"{name} must be non-empty text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    return tuple(_required_text(item, name) for item in _list(value, name))


def _canonical_texts(value: Any, name: str) -> list[str]:
    if not isinstance(value, tuple):
        raise _PayloadDecodeError(f"{name} must be a tuple")
    return sorted(_required_text(item, name) for item in value)


def _enum(value: Any, enum_type: type[StrEnum], name: str) -> StrEnum:
    if not isinstance(value, str):
        raise _PayloadDecodeError(f"{name} must be text")
    try:
        return enum_type(value)
    except ValueError as error:
        raise _PayloadDecodeError(f"{name} is invalid") from error


def _enum_value(value: Any, enum_type: type[StrEnum], name: str) -> str:
    return _enum(value, enum_type, name).value


def _non_negative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _PayloadDecodeError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _PayloadDecodeError(f"{name} must be a positive integer")
    return value


def _confidence(value: Any) -> float | int:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value != value
        or value in (float("inf"), float("-inf"))
        or not 0.0 <= value <= 1.0
    ):
        raise _PayloadDecodeError(
            "confidence must be a finite number from 0.0 through 1.0"
        )
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _PayloadDecodeError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise _PayloadDecodeError(f"invalid JSON constant: {value}")


def _raise(code: GlossarySnapshotSerializationErrorCode, message: str) -> NoReturn:
    raise GlossarySnapshotSerializationError(code, message)


class _PayloadDecodeError(ValueError):
    pass


_SNAPSHOT_FIELDS = frozenset(
    {
        "entries",
        "evidence",
        "policy_version",
        "profile_signature",
        "schema_version",
        "snapshot_id",
        "source_language",
        "target_language",
    }
)
_ENTRY_FIELDS = frozenset(
    {
        "aliases",
        "category",
        "confidence",
        "entry_id",
        "evidence_refs",
        "forbidden_variants",
        "grammatical_gender",
        "layer",
        "morphology_notes",
        "profile_rule_ids",
        "schema_version",
        "source_canonical",
        "status",
        "strategy",
        "target_canonical",
        "target_variants",
    }
)
_EVIDENCE_FIELDS = frozenset(
    {
        "evidence_id",
        "evidence_type",
        "occurrence_count",
        "offset_bucket",
        "raw_excerpt",
        "source_block_id",
        "source_scope",
        "surface",
        "unit_sequence",
    }
)
