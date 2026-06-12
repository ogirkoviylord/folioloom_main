from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

GLOSSARY_ENTRY_SCHEMA_VERSION = "glossary-entry-v1"
GLOSSARY_SNAPSHOT_SCHEMA_VERSION = "glossary-snapshot-v1"
GLOSSARY_SIGNATURE_VERSION = "glossary-signature-v1"


class GlossaryLayer(StrEnum):
    HARD = "hard"
    SOFT = "soft"
    DIAGNOSTIC = "diagnostic"


class GlossaryEntryStatus(StrEnum):
    AUTO_DETECTED = "auto_detected"
    VALIDATOR_ACCEPTED = "validator_accepted"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"
    OWNER_PINNED = "owner_pinned"
    LOCKED = "locked"
    UNKNOWN = "unknown"


class GlossaryEntryCategory(StrEnum):
    NAME = "name"
    TERM = "term"
    ENTITY = "entity"
    STYLE_NOTE = "style_note"
    MORPHOLOGY_NOTE = "morphology_note"


class GlossaryStrategy(StrEnum):
    PRESERVE_EXACT = "preserve_exact"
    PRESERVE_OFFICIAL = "preserve_official"
    TRANSLITERATE = "transliterate"
    TRANSCRIBE = "transcribe"
    TRANSLATE_MEANING = "translate_meaning"
    CONTEXTUAL = "contextual"
    DO_NOT_TRANSLATE = "do_not_translate"
    UNKNOWN = "unknown"


class GlossaryGender(StrEnum):
    MASCULINE = "masculine"
    FEMININE = "feminine"
    NEUTER = "neuter"
    COMMON = "common"
    MIXED = "mixed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class GlossaryEvidenceType(StrEnum):
    EXACT_REPEAT = "exact_repeat"
    SOURCE_ANCHOR = "source_anchor"
    PRONOUN = "pronoun"
    TITLE = "title"
    APPOSITION = "apposition"
    QUOTE_ATTRIBUTION = "quote_attribution"
    HEADING = "heading"
    OWNER_PIN = "owner_pin"
    UNKNOWN = "unknown"


class GlossaryEvidenceSurface(StrEnum):
    BODY = "body"
    NAV = "nav"
    TOC = "toc"
    METADATA = "metadata"
    FOOTNOTE = "footnote"
    HEADING = "heading"
    UNKNOWN = "unknown"


class GlossaryValidationCode(StrEnum):
    MISSING_FIELD = "missing_field"
    INVALID_SCHEMA_VERSION = "invalid_schema_version"
    INVALID_ENUM = "invalid_enum"
    INVALID_CONFIDENCE = "invalid_confidence"
    INVALID_SOURCE_ANCHOR = "invalid_source_anchor"
    MISSING_EVIDENCE = "missing_evidence"
    DUPLICATE_ID = "duplicate_id"
    UNSUPPORTED_LAYER_STATUS = "unsupported_layer_status"
    RAW_TEXT_NOT_ALLOWED = "raw_text_not_allowed"


@dataclass(frozen=True)
class GlossaryEvidenceRef:
    evidence_id: str
    evidence_type: GlossaryEvidenceType | str
    unit_sequence: int
    source_block_id: str
    source_scope: str = "global"
    surface: GlossaryEvidenceSurface | str = GlossaryEvidenceSurface.UNKNOWN
    occurrence_count: int = 1
    offset_bucket: str = "unknown"
    raw_excerpt: str | None = None


@dataclass(frozen=True)
class GlossaryEntry:
    entry_id: str
    category: GlossaryEntryCategory | str
    layer: GlossaryLayer | str
    status: GlossaryEntryStatus | str
    source_canonical: str
    evidence_refs: tuple[str, ...]
    confidence: float
    schema_version: str = GLOSSARY_ENTRY_SCHEMA_VERSION
    aliases: tuple[str, ...] = ()
    target_canonical: str | None = None
    target_variants: tuple[str, ...] = ()
    forbidden_variants: tuple[str, ...] = ()
    strategy: GlossaryStrategy | str = GlossaryStrategy.UNKNOWN
    grammatical_gender: GlossaryGender | str = GlossaryGender.UNKNOWN
    morphology_notes: tuple[str, ...] = ()
    profile_rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GlossarySnapshot:
    snapshot_id: str
    source_language: str
    target_language: str
    entries: tuple[GlossaryEntry, ...]
    evidence: tuple[GlossaryEvidenceRef, ...]
    schema_version: str = GLOSSARY_SNAPSHOT_SCHEMA_VERSION
    policy_version: str = "glossary-policy-v1"
    profile_signature: str = "book-profile:none"


@dataclass(frozen=True)
class GlossaryValidationIssue:
    code: GlossaryValidationCode
    path: str
    message: str


@dataclass(frozen=True)
class GlossaryValidationResult:
    issues: tuple[GlossaryValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_glossary_snapshot(
    snapshot: GlossarySnapshot,
    *,
    allow_raw_diagnostics: bool = False,
) -> GlossaryValidationResult:
    issues: list[GlossaryValidationIssue] = []
    if snapshot.schema_version != GLOSSARY_SNAPSHOT_SCHEMA_VERSION:
        _add_issue(
            issues,
            GlossaryValidationCode.INVALID_SCHEMA_VERSION,
            "schema_version",
            f"schema_version must be {GLOSSARY_SNAPSHOT_SCHEMA_VERSION}.",
        )
    if not _non_empty_text(snapshot.snapshot_id):
        _add_issue(
            issues,
            GlossaryValidationCode.MISSING_FIELD,
            "snapshot_id",
            "snapshot_id is required.",
        )
    if not _non_empty_text(snapshot.source_language):
        _add_issue(
            issues,
            GlossaryValidationCode.MISSING_FIELD,
            "source_language",
            "source_language is required.",
        )
    if not _non_empty_text(snapshot.target_language):
        _add_issue(
            issues,
            GlossaryValidationCode.MISSING_FIELD,
            "target_language",
            "target_language is required.",
        )
    if not _non_empty_text(snapshot.policy_version):
        _add_issue(
            issues,
            GlossaryValidationCode.MISSING_FIELD,
            "policy_version",
            "policy_version is required.",
        )
    if not _non_empty_text(snapshot.profile_signature):
        _add_issue(
            issues,
            GlossaryValidationCode.MISSING_FIELD,
            "profile_signature",
            "profile_signature is required.",
        )

    evidence_ids: set[str] = set()
    for index, evidence in enumerate(snapshot.evidence):
        path = f"evidence[{index}]"
        if not _non_empty_text(evidence.evidence_id):
            _add_issue(
                issues,
                GlossaryValidationCode.MISSING_FIELD,
                f"{path}.evidence_id",
                "evidence_id is required.",
            )
        elif evidence.evidence_id in evidence_ids:
            _add_issue(
                issues,
                GlossaryValidationCode.DUPLICATE_ID,
                f"{path}.evidence_id",
                "evidence_id must be unique.",
            )
        else:
            evidence_ids.add(evidence.evidence_id)
        _validate_evidence_ref(
            evidence,
            issues=issues,
            path=path,
            allow_raw_diagnostics=allow_raw_diagnostics,
        )

    entry_ids: set[str] = set()
    for index, entry in enumerate(snapshot.entries):
        path = f"entries[{index}]"
        if not _non_empty_text(entry.entry_id):
            _add_issue(
                issues,
                GlossaryValidationCode.MISSING_FIELD,
                f"{path}.entry_id",
                "entry_id is required.",
            )
        elif entry.entry_id in entry_ids:
            _add_issue(
                issues,
                GlossaryValidationCode.DUPLICATE_ID,
                f"{path}.entry_id",
                "entry_id must be unique.",
            )
        else:
            entry_ids.add(entry.entry_id)
        _validate_entry(entry, evidence_ids=evidence_ids, issues=issues, path=path)

    return GlossaryValidationResult(issues=tuple(issues))


def glossary_entry_signature(entry: GlossaryEntry) -> str:
    payload = {
        "schema_version": entry.schema_version,
        "entry_id": entry.entry_id,
        "category": _enum_signature_value(entry.category),
        "layer": _enum_signature_value(entry.layer),
        "status": _enum_signature_value(entry.status),
        "source_canonical_digest": _text_digest(entry.source_canonical),
        "alias_digests": _text_digest_sequence(entry.aliases),
        "target_canonical_digest": _optional_text_digest(entry.target_canonical),
        "target_variant_digests": _text_digest_sequence(entry.target_variants),
        "forbidden_variant_digests": _text_digest_sequence(entry.forbidden_variants),
        "evidence_refs": sorted(str(ref) for ref in entry.evidence_refs),
        "confidence": _confidence_signature_value(entry.confidence),
        "strategy": _enum_signature_value(entry.strategy),
        "grammatical_gender": _enum_signature_value(entry.grammatical_gender),
        "morphology_note_digests": _text_digest_sequence(entry.morphology_notes),
        "profile_rule_ids": sorted(str(rule_id) for rule_id in entry.profile_rule_ids),
    }
    return f"glossary-entry:v1:{_payload_digest(payload)}"


def glossary_snapshot_signature(snapshot: GlossarySnapshot) -> str:
    payload = {
        "signature_version": GLOSSARY_SIGNATURE_VERSION,
        "schema_version": snapshot.schema_version,
        "source_language": snapshot.source_language.strip().lower(),
        "target_language": snapshot.target_language.strip().lower(),
        "policy_version": snapshot.policy_version,
        "profile_signature": snapshot.profile_signature,
        "entry_signatures": sorted(
            glossary_entry_signature(entry) for entry in snapshot.entries
        ),
        "evidence_signatures": sorted(
            _evidence_signature(evidence) for evidence in snapshot.evidence
        ),
    }
    return f"glossary-snapshot:v1:{_payload_digest(payload)}"


def _validate_evidence_ref(
    evidence: GlossaryEvidenceRef,
    *,
    issues: list[GlossaryValidationIssue],
    path: str,
    allow_raw_diagnostics: bool,
) -> None:
    _validate_enum(
        evidence.evidence_type,
        GlossaryEvidenceType,
        issues=issues,
        path=f"{path}.evidence_type",
    )
    _validate_enum(
        evidence.surface,
        GlossaryEvidenceSurface,
        issues=issues,
        path=f"{path}.surface",
    )
    if (
        not isinstance(evidence.unit_sequence, int)
        or isinstance(evidence.unit_sequence, bool)
        or evidence.unit_sequence < 0
    ):
        _add_issue(
            issues,
            GlossaryValidationCode.INVALID_SOURCE_ANCHOR,
            f"{path}.unit_sequence",
            "unit_sequence must be a non-negative integer.",
        )
    if not _non_empty_text(evidence.source_block_id):
        _add_issue(
            issues,
            GlossaryValidationCode.INVALID_SOURCE_ANCHOR,
            f"{path}.source_block_id",
            "source_block_id is required.",
        )
    if not _non_empty_text(evidence.source_scope):
        _add_issue(
            issues,
            GlossaryValidationCode.INVALID_SOURCE_ANCHOR,
            f"{path}.source_scope",
            "source_scope is required.",
        )
    if (
        not isinstance(evidence.occurrence_count, int)
        or isinstance(evidence.occurrence_count, bool)
        or evidence.occurrence_count < 1
    ):
        _add_issue(
            issues,
            GlossaryValidationCode.INVALID_SOURCE_ANCHOR,
            f"{path}.occurrence_count",
            "occurrence_count must be a positive integer.",
        )
    if evidence.raw_excerpt and not allow_raw_diagnostics:
        _add_issue(
            issues,
            GlossaryValidationCode.RAW_TEXT_NOT_ALLOWED,
            f"{path}.raw_excerpt",
            "raw excerpts require an approved owner-only diagnostic artifact.",
        )


def _validate_entry(
    entry: GlossaryEntry,
    *,
    evidence_ids: set[str],
    issues: list[GlossaryValidationIssue],
    path: str,
) -> None:
    if entry.schema_version != GLOSSARY_ENTRY_SCHEMA_VERSION:
        _add_issue(
            issues,
            GlossaryValidationCode.INVALID_SCHEMA_VERSION,
            f"{path}.schema_version",
            f"schema_version must be {GLOSSARY_ENTRY_SCHEMA_VERSION}.",
        )
    if not _non_empty_text(entry.source_canonical):
        _add_issue(
            issues,
            GlossaryValidationCode.MISSING_FIELD,
            f"{path}.source_canonical",
            "source_canonical is required.",
        )
    _validate_enum(
        entry.category,
        GlossaryEntryCategory,
        issues=issues,
        path=f"{path}.category",
    )
    layer = _validate_enum(
        entry.layer,
        GlossaryLayer,
        issues=issues,
        path=f"{path}.layer",
    )
    status = _validate_enum(
        entry.status,
        GlossaryEntryStatus,
        issues=issues,
        path=f"{path}.status",
    )
    _validate_enum(
        entry.strategy,
        GlossaryStrategy,
        issues=issues,
        path=f"{path}.strategy",
    )
    _validate_enum(
        entry.grammatical_gender,
        GlossaryGender,
        issues=issues,
        path=f"{path}.grammatical_gender",
    )

    if not _valid_confidence(entry.confidence):
        _add_issue(
            issues,
            GlossaryValidationCode.INVALID_CONFIDENCE,
            f"{path}.confidence",
            "confidence must be a finite number from 0.0 through 1.0.",
        )
    if not entry.evidence_refs:
        _add_issue(
            issues,
            GlossaryValidationCode.MISSING_EVIDENCE,
            f"{path}.evidence_refs",
            "at least one evidence reference is required.",
        )
    for evidence_ref in entry.evidence_refs:
        if evidence_ref not in evidence_ids:
            _add_issue(
                issues,
                GlossaryValidationCode.MISSING_EVIDENCE,
                f"{path}.evidence_refs",
                f"evidence reference {evidence_ref!r} is not defined.",
            )

    if layer is not None and status is not None:
        _validate_layer_status(layer=layer, status=status, issues=issues, path=path)


def _validate_layer_status(
    *,
    layer: GlossaryLayer,
    status: GlossaryEntryStatus,
    issues: list[GlossaryValidationIssue],
    path: str,
) -> None:
    if layer is GlossaryLayer.HARD and status not in {
        GlossaryEntryStatus.VALIDATOR_ACCEPTED,
        GlossaryEntryStatus.OWNER_PINNED,
        GlossaryEntryStatus.LOCKED,
    }:
        _add_issue(
            issues,
            GlossaryValidationCode.UNSUPPORTED_LAYER_STATUS,
            f"{path}.status",
            "hard entries must be accepted, owner_pinned, or locked.",
        )
    if status is GlossaryEntryStatus.REJECTED and layer is not GlossaryLayer.DIAGNOSTIC:
        _add_issue(
            issues,
            GlossaryValidationCode.UNSUPPORTED_LAYER_STATUS,
            f"{path}.status",
            "rejected entries belong in the diagnostic layer.",
        )
    if status is GlossaryEntryStatus.UNKNOWN and layer is GlossaryLayer.HARD:
        _add_issue(
            issues,
            GlossaryValidationCode.UNSUPPORTED_LAYER_STATUS,
            f"{path}.status",
            "hard entries cannot use unknown status.",
        )


def _validate_enum(
    value: Any,
    enum_type: type[StrEnum],
    *,
    issues: list[GlossaryValidationIssue],
    path: str,
) -> StrEnum | None:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError:
            pass
    _add_issue(
        issues,
        GlossaryValidationCode.INVALID_ENUM,
        path,
        f"{path} must be one of: {', '.join(item.value for item in enum_type)}.",
    )
    return None


def _evidence_signature(evidence: GlossaryEvidenceRef) -> str:
    payload = {
        "evidence_id": evidence.evidence_id,
        "evidence_type": _enum_signature_value(evidence.evidence_type),
        "unit_sequence": evidence.unit_sequence,
        "source_block_id": evidence.source_block_id,
        "source_scope": evidence.source_scope,
        "surface": _enum_signature_value(evidence.surface),
        "occurrence_count": evidence.occurrence_count,
        "offset_bucket": evidence.offset_bucket,
    }
    return f"glossary-evidence:v1:{_payload_digest(payload)}"


def _add_issue(
    issues: list[GlossaryValidationIssue],
    code: GlossaryValidationCode,
    path: str,
    message: str,
) -> None:
    issues.append(GlossaryValidationIssue(code=code, path=path, message=message))


def _valid_confidence(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _enum_signature_value(value: Any) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)


def _confidence_signature_value(value: Any) -> str:
    if _valid_confidence(value):
        return f"{float(value):.6f}"
    return str(value)


def _optional_text_digest(value: str | None) -> str | None:
    if value is None:
        return None
    return _text_digest(value)


def _text_digest_sequence(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(_text_digest(str(value)) for value in values))


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _payload_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
