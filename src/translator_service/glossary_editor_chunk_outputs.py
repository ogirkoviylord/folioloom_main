from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.glossary_contracts import (
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryGender,
    GlossaryLayer,
    GlossaryStrategy,
)
from translator_service.glossary_editor_packets import GlossaryEditorPacket
from translator_service.glossary_role_validators import GlossaryRoleId
from translator_service.json_utils import (
    DuplicateJsonKeyError,
    json_object_without_duplicate_keys,
)
from translator_service.model_output_safety import validate_model_output_safety

CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION = "chunked-glossary-editor-output-v1"
CHUNKED_GLOSSARY_EDITOR_MERGE_SCHEMA_VERSION = "chunked-glossary-editor-merge-v1"
DEFAULT_MAX_CHUNKED_GLOSSARY_EDITOR_OUTPUT_BYTES = 24_000
LOW_CONFIDENCE_SEMANTIC_THRESHOLD = 0.70


class ChunkedGlossaryEditorOutputStatus(StrEnum):
    ACCEPTED = "accepted"
    ACCEPTED_LOW_CONFIDENCE = "accepted_low_confidence"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    FAILED = "failed"


class ChunkedGlossaryEditorFindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class ChunkedGlossaryEditorFindingCode(StrEnum):
    INVALID_CHUNK = "invalid_chunk"
    DUPLICATE_ENTRY_OUTPUT = "duplicate_entry_output"
    CONFLICTING_ALIASES = "conflicting_aliases"
    CONFLICTING_TARGET_VARIANTS = "conflicting_target_variants"
    MISSING_EVIDENCE_REFS = "missing_evidence_refs"
    LOW_CONFIDENCE_SEMANTICS = "low_confidence_semantics"
    SEMANTIC_REVIEW_REQUIRED = "semantic_review_required"


class ChunkedGlossaryEditorValidationCode(StrEnum):
    INVALID_JSON = "invalid_json"
    WRONG_ROOT = "wrong_root"
    UNEXPECTED_KEY = "unexpected_key"
    MISSING_FIELD = "missing_field"
    INVALID_SCHEMA_VERSION = "invalid_schema_version"
    INVALID_PACKET_REF = "invalid_packet_ref"
    INVALID_ENUM = "invalid_enum"
    INVALID_CONFIDENCE = "invalid_confidence"
    OVERSIZED_PAYLOAD = "oversized_payload"
    MISSING_EVIDENCE = "missing_evidence"
    INVALID_ENTRY_REF = "invalid_entry_ref"
    DUPLICATE_ID = "duplicate_id"
    UNSUPPORTED_HARD_PROMOTION = "unsupported_hard_promotion"
    UNSUPPORTED_LAYER_STATUS = "unsupported_layer_status"
    UNSAFE_MODEL_OUTPUT = "unsafe_model_output"


@dataclass(frozen=True)
class ChunkedGlossaryEditorValidationIssue:
    code: ChunkedGlossaryEditorValidationCode
    path: str
    message: str


@dataclass(frozen=True)
class ChunkedGlossaryEditorValidationResult:
    issues: tuple[ChunkedGlossaryEditorValidationIssue, ...] = ()
    packet_id: str | None = None
    packet_signature: str | None = None
    document: Mapping[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class ChunkedGlossaryEditorEntryProposal:
    entry_id: str
    packet_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    category: str
    layer: str
    status: str
    aliases: tuple[str, ...]
    target_canonical: str | None
    target_variants: tuple[str, ...]
    forbidden_variants: tuple[str, ...]
    strategy: str
    grammatical_gender: str
    confidence: float
    needs_review: bool


@dataclass(frozen=True)
class ChunkedGlossaryEditorMergeFinding:
    finding_id: str
    code: ChunkedGlossaryEditorFindingCode
    severity: ChunkedGlossaryEditorFindingSeverity
    packet_ids: tuple[str, ...]
    entry_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ChunkedGlossaryEditorMergeResult:
    schema_version: str
    merge_signature: str
    proposed_entries: tuple[ChunkedGlossaryEditorEntryProposal, ...]
    findings: tuple[ChunkedGlossaryEditorMergeFinding, ...]
    invalid_packet_ids: tuple[str, ...]

    @property
    def has_blockers(self) -> bool:
        return any(
            finding.severity is ChunkedGlossaryEditorFindingSeverity.BLOCKER
            for finding in self.findings
        )


_ROOT_KEYS = {
    "output_schema_version",
    "role_id",
    "role_version",
    "status",
    "packet_id",
    "packet_signature",
    "glossary_signature",
    "profile_signature",
    "confidence",
    "evidence_refs",
    "proposed_entries",
    "rejected_entries",
    "findings",
}

_ENTRY_KEYS = {
    "entry_id",
    "category",
    "layer",
    "status",
    "aliases",
    "target_canonical",
    "target_variants",
    "forbidden_variants",
    "strategy",
    "grammatical_gender",
    "confidence",
    "evidence_refs",
    "profile_rule_ids",
}

_REJECTED_ENTRY_KEYS = {"entry_id", "reason", "confidence", "evidence_refs"}
_FINDING_KEYS = {
    "finding_id",
    "kind",
    "severity",
    "entry_ids",
    "evidence_refs",
    "message",
}
_FORBIDDEN_RAW_TEXT_KEYS = {
    "raw_excerpt",
    "raw_text",
    "source_text",
    "source_canonical",
    "prompt",
    "provider_request",
    "provider_response",
    "system_prompt",
}
_MODEL_FORBIDDEN_STATUSES = {
    GlossaryEntryStatus.OWNER_PINNED,
    GlossaryEntryStatus.LOCKED,
}


def validate_chunked_glossary_editor_output(
    raw_json: str,
    *,
    packet: GlossaryEditorPacket,
    max_bytes: int = DEFAULT_MAX_CHUNKED_GLOSSARY_EDITOR_OUTPUT_BYTES,
) -> ChunkedGlossaryEditorValidationResult:
    issues: list[ChunkedGlossaryEditorValidationIssue] = []
    if len(raw_json.encode("utf-8")) > max_bytes:
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.OVERSIZED_PAYLOAD,
            "$",
            f"chunked glossary editor output must not exceed {max_bytes} bytes.",
        )
        return ChunkedGlossaryEditorValidationResult(
            issues=tuple(issues),
            packet_id=packet.packet_id,
            packet_signature=packet.packet_signature,
        )

    document = _load_json_document(raw_json, issues)
    if document is None:
        return ChunkedGlossaryEditorValidationResult(
            issues=tuple(issues),
            packet_id=packet.packet_id,
            packet_signature=packet.packet_signature,
        )

    allowed_evidence = frozenset(packet.evidence_ids)
    allowed_entries = frozenset(packet.entry_ids)
    _validate_keys(document, _ROOT_KEYS, issues, "$")
    for key in _ROOT_KEYS:
        if key not in document:
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                key,
                f"{key} is required.",
            )

    if (
        document.get("output_schema_version")
        != CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION
    ):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.INVALID_SCHEMA_VERSION,
            "output_schema_version",
            "output_schema_version must be "
            f"{CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION}.",
        )
    if document.get("role_id") != GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER.value:
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.INVALID_ENUM,
            "role_id",
            "role_id must be pro_glossary_editor_normalizer.",
        )
    if not _non_empty_text(document.get("role_version")):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
            "role_version",
            "role_version is required.",
        )
    _validate_enum(
        document.get("status"),
        ChunkedGlossaryEditorOutputStatus,
        issues,
        "status",
    )
    _validate_packet_refs(document, packet, issues)
    _validate_confidence(document.get("confidence"), issues, "confidence")
    _validate_evidence_refs(
        document.get("evidence_refs"),
        allowed_evidence,
        issues,
        "evidence_refs",
        required=True,
    )
    _validate_proposed_entries(
        document.get("proposed_entries"),
        allowed_entries=allowed_entries,
        allowed_evidence=allowed_evidence,
        issues=issues,
    )
    _validate_rejected_entries(
        document.get("rejected_entries"),
        allowed_entries=allowed_entries,
        allowed_evidence=allowed_evidence,
        issues=issues,
    )
    _validate_output_findings(
        document.get("findings"),
        allowed_entries=allowed_entries,
        allowed_evidence=allowed_evidence,
        issues=issues,
    )
    _validate_no_forbidden_raw_text_keys(document, issues)
    _validate_safe_strings(document, issues)

    return ChunkedGlossaryEditorValidationResult(
        issues=tuple(issues),
        packet_id=packet.packet_id,
        packet_signature=packet.packet_signature,
        document=document if not issues else None,
    )


def merge_chunked_glossary_editor_outputs(
    validation_results: Sequence[ChunkedGlossaryEditorValidationResult],
) -> ChunkedGlossaryEditorMergeResult:
    findings: list[ChunkedGlossaryEditorMergeFinding] = []
    invalid_packet_ids: list[str] = []
    proposals_by_entry_id: dict[str, list[dict[str, Any]]] = {}

    for index, result in enumerate(validation_results):
        packet_id = result.packet_id or f"unknown-packet:{index}"
        if not result.valid or result.document is None:
            invalid_packet_ids.append(packet_id)
            findings.append(
                _finding(
                    code=ChunkedGlossaryEditorFindingCode.INVALID_CHUNK,
                    severity=ChunkedGlossaryEditorFindingSeverity.BLOCKER,
                    packet_ids=(packet_id,),
                    entry_ids=(),
                    evidence_refs=(),
                    message="Invalid chunk output was excluded from merge.",
                )
            )
            if any(
                issue.code is ChunkedGlossaryEditorValidationCode.MISSING_EVIDENCE
                for issue in result.issues
            ):
                findings.append(
                    _finding(
                        code=ChunkedGlossaryEditorFindingCode.MISSING_EVIDENCE_REFS,
                        severity=ChunkedGlossaryEditorFindingSeverity.BLOCKER,
                        packet_ids=(packet_id,),
                        entry_ids=(),
                        evidence_refs=(),
                        message="Invalid chunk output contained missing evidence refs.",
                    )
                )
            continue
        for entry in result.document.get("proposed_entries", ()):
            if isinstance(entry, dict):
                proposals_by_entry_id.setdefault(str(entry.get("entry_id")), []).append(
                    {"packet_id": packet_id, "entry": entry}
                )

    proposed_entries: list[ChunkedGlossaryEditorEntryProposal] = []
    for entry_id in sorted(proposals_by_entry_id):
        proposed = proposals_by_entry_id[entry_id]
        packet_ids = tuple(sorted({str(item["packet_id"]) for item in proposed}))
        entries = tuple(item["entry"] for item in proposed)
        evidence_refs = tuple(
            sorted(
                {
                    str(ref)
                    for entry in entries
                    for ref in entry.get("evidence_refs", ())
                    if isinstance(ref, str)
                }
            )
        )
        if len(proposed) > 1:
            findings.append(
                _finding(
                    code=ChunkedGlossaryEditorFindingCode.DUPLICATE_ENTRY_OUTPUT,
                    severity=ChunkedGlossaryEditorFindingSeverity.WARNING,
                    packet_ids=packet_ids,
                    entry_ids=(entry_id,),
                    evidence_refs=evidence_refs,
                    message="Entry appeared in more than one valid chunk output.",
                )
            )
        if not evidence_refs:
            findings.append(
                _finding(
                    code=ChunkedGlossaryEditorFindingCode.MISSING_EVIDENCE_REFS,
                    severity=ChunkedGlossaryEditorFindingSeverity.BLOCKER,
                    packet_ids=packet_ids,
                    entry_ids=(entry_id,),
                    evidence_refs=(),
                    message="Merged entry has no evidence references.",
                )
            )
        if _sequence_values_conflict(entries, "aliases"):
            findings.append(
                _finding(
                    code=ChunkedGlossaryEditorFindingCode.CONFLICTING_ALIASES,
                    severity=ChunkedGlossaryEditorFindingSeverity.WARNING,
                    packet_ids=packet_ids,
                    entry_ids=(entry_id,),
                    evidence_refs=evidence_refs,
                    message="Duplicate chunk outputs disagree on aliases.",
                )
            )
        if _target_values_conflict(entries):
            findings.append(
                _finding(
                    code=(
                        ChunkedGlossaryEditorFindingCode.CONFLICTING_TARGET_VARIANTS
                    ),
                    severity=ChunkedGlossaryEditorFindingSeverity.BLOCKER,
                    packet_ids=packet_ids,
                    entry_ids=(entry_id,),
                    evidence_refs=evidence_refs,
                    message="Duplicate chunk outputs disagree on target variants.",
                )
            )

        winner = _winner_entry(entries)
        confidence = float(winner["confidence"])
        low_confidence_present = any(
            float(entry["confidence"]) < LOW_CONFIDENCE_SEMANTIC_THRESHOLD
            for entry in entries
        )
        semantic_review_required = any(
            _semantic_review_required(entry) for entry in entries
        )
        if low_confidence_present:
            findings.append(
                _finding(
                    code=ChunkedGlossaryEditorFindingCode.LOW_CONFIDENCE_SEMANTICS,
                    severity=ChunkedGlossaryEditorFindingSeverity.WARNING,
                    packet_ids=packet_ids,
                    entry_ids=(entry_id,),
                    evidence_refs=evidence_refs,
                    message="Entry semantics are below the local confidence threshold.",
                )
            )
        if semantic_review_required:
            findings.append(
                _finding(
                    code=ChunkedGlossaryEditorFindingCode.SEMANTIC_REVIEW_REQUIRED,
                    severity=ChunkedGlossaryEditorFindingSeverity.INFO,
                    packet_ids=packet_ids,
                    entry_ids=(entry_id,),
                    evidence_refs=evidence_refs,
                    message=(
                        "Model-supplied grammatical gender/name semantics require "
                        "evidence-backed review."
                    ),
                )
            )
        proposed_entries.append(
            ChunkedGlossaryEditorEntryProposal(
                entry_id=entry_id,
                packet_ids=packet_ids,
                evidence_refs=evidence_refs,
                category=str(winner["category"]),
                layer=str(winner["layer"]),
                status=str(winner["status"]),
                aliases=_normalized_text_tuple(winner.get("aliases")),
                target_canonical=_optional_text(winner.get("target_canonical")),
                target_variants=_normalized_text_tuple(winner.get("target_variants")),
                forbidden_variants=_normalized_text_tuple(
                    winner.get("forbidden_variants")
                ),
                strategy=str(winner["strategy"]),
                grammatical_gender=str(winner["grammatical_gender"]),
                confidence=confidence,
                needs_review=semantic_review_required
                or low_confidence_present
                or _merge_has_entry_blocker(findings, entry_id),
            )
        )

    proposed_entries_tuple = tuple(
        sorted(proposed_entries, key=lambda entry: entry.entry_id)
    )
    findings_tuple = tuple(sorted(findings, key=_merge_finding_sort_key))
    payload = {
        "schema_version": CHUNKED_GLOSSARY_EDITOR_MERGE_SCHEMA_VERSION,
        "proposed_entries": [
            _entry_proposal_payload(entry) for entry in proposed_entries_tuple
        ],
        "findings": [_merge_finding_payload(finding) for finding in findings_tuple],
        "invalid_packet_ids": sorted(invalid_packet_ids),
    }
    return ChunkedGlossaryEditorMergeResult(
        schema_version=CHUNKED_GLOSSARY_EDITOR_MERGE_SCHEMA_VERSION,
        merge_signature=f"chunked-glossary-editor-merge:v1:{_payload_digest(payload)}",
        proposed_entries=proposed_entries_tuple,
        findings=findings_tuple,
        invalid_packet_ids=tuple(sorted(invalid_packet_ids)),
    )


def chunked_glossary_editor_merge_payload(
    result: ChunkedGlossaryEditorMergeResult,
) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "merge_signature": result.merge_signature,
        "proposed_entries": [
            _entry_proposal_payload(entry) for entry in result.proposed_entries
        ],
        "findings": [_merge_finding_payload(finding) for finding in result.findings],
        "invalid_packet_ids": list(result.invalid_packet_ids),
        "has_blockers": result.has_blockers,
    }


def serialize_chunked_glossary_editor_merge(
    result: ChunkedGlossaryEditorMergeResult,
) -> str:
    return json.dumps(
        chunked_glossary_editor_merge_payload(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_packet_refs(
    document: Mapping[str, Any],
    packet: GlossaryEditorPacket,
    issues: list[ChunkedGlossaryEditorValidationIssue],
) -> None:
    expected_refs = {
        "packet_id": packet.packet_id,
        "packet_signature": packet.packet_signature,
        "glossary_signature": packet.glossary_signature,
        "profile_signature": packet.profile_signature,
    }
    for key, expected in expected_refs.items():
        if document.get(key) != expected:
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.INVALID_PACKET_REF,
                key,
                f"{key} must match the source GlossaryEditorPacket.",
            )


def _validate_proposed_entries(
    value: Any,
    *,
    allowed_entries: frozenset[str],
    allowed_evidence: frozenset[str],
    issues: list[ChunkedGlossaryEditorValidationIssue],
) -> None:
    if not isinstance(value, list):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
            "proposed_entries",
            "proposed_entries must be a list.",
        )
        return
    entry_ids: set[str] = set()
    for index, item in enumerate(value):
        path = f"proposed_entries[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                path,
                "proposed entry must be an object.",
            )
            continue
        _validate_keys(item, _ENTRY_KEYS, issues, path)
        entry_id = _validate_entry_ref(
            item.get("entry_id"),
            allowed_entries,
            issues,
            f"{path}.entry_id",
        )
        if entry_id is not None:
            if entry_id in entry_ids:
                _add_issue(
                    issues,
                    ChunkedGlossaryEditorValidationCode.DUPLICATE_ID,
                    f"{path}.entry_id",
                    "entry_id must be unique within one packet output.",
                )
            entry_ids.add(entry_id)
        _validate_entry_shape(item, allowed_evidence, issues, path)


def _validate_entry_shape(
    item: Mapping[str, Any],
    allowed_evidence: frozenset[str],
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str,
) -> None:
    _validate_enum(
        item.get("category"),
        GlossaryEntryCategory,
        issues,
        f"{path}.category",
    )
    layer = _validate_enum(item.get("layer"), GlossaryLayer, issues, f"{path}.layer")
    status = _validate_enum(
        item.get("status"),
        GlossaryEntryStatus,
        issues,
        f"{path}.status",
    )
    _validate_enum(item.get("strategy"), GlossaryStrategy, issues, f"{path}.strategy")
    _validate_enum(
        item.get("grammatical_gender"),
        GlossaryGender,
        issues,
        f"{path}.grammatical_gender",
    )
    if layer is GlossaryLayer.HARD:
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.UNSUPPORTED_HARD_PROMOTION,
            f"{path}.layer",
            "chunked glossary editor output cannot promote entries to hard.",
        )
    if status in _MODEL_FORBIDDEN_STATUSES:
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.UNSUPPORTED_LAYER_STATUS,
            f"{path}.status",
            "model output cannot claim owner_pinned or locked glossary status.",
        )
    if (
        layer is not None
        and status is GlossaryEntryStatus.REJECTED
        and layer is not GlossaryLayer.DIAGNOSTIC
    ):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.UNSUPPORTED_LAYER_STATUS,
            f"{path}.status",
            "rejected entries must remain diagnostic.",
        )
    _validate_text_sequence(item.get("aliases"), issues, f"{path}.aliases")
    _validate_optional_text(
        item.get("target_canonical"),
        issues,
        f"{path}.target_canonical",
    )
    _validate_text_sequence(
        item.get("target_variants"),
        issues,
        f"{path}.target_variants",
    )
    _validate_text_sequence(
        item.get("forbidden_variants"),
        issues,
        f"{path}.forbidden_variants",
    )
    _validate_text_sequence(
        item.get("profile_rule_ids"),
        issues,
        f"{path}.profile_rule_ids",
    )
    _validate_confidence(item.get("confidence"), issues, f"{path}.confidence")
    _validate_evidence_refs(
        item.get("evidence_refs"),
        allowed_evidence,
        issues,
        f"{path}.evidence_refs",
        required=True,
    )


def _validate_rejected_entries(
    value: Any,
    *,
    allowed_entries: frozenset[str],
    allowed_evidence: frozenset[str],
    issues: list[ChunkedGlossaryEditorValidationIssue],
) -> None:
    if not isinstance(value, list):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
            "rejected_entries",
            "rejected_entries must be a list.",
        )
        return
    rejected_ids: set[str] = set()
    for index, item in enumerate(value):
        path = f"rejected_entries[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                path,
                "rejected entry must be an object.",
            )
            continue
        _validate_keys(item, _REJECTED_ENTRY_KEYS, issues, path)
        entry_id = _validate_entry_ref(
            item.get("entry_id"),
            allowed_entries,
            issues,
            f"{path}.entry_id",
        )
        if entry_id is not None:
            if entry_id in rejected_ids:
                _add_issue(
                    issues,
                    ChunkedGlossaryEditorValidationCode.DUPLICATE_ID,
                    f"{path}.entry_id",
                    "entry_id must be unique within rejected_entries.",
                )
            rejected_ids.add(entry_id)
        if not _non_empty_text(item.get("reason")):
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                f"{path}.reason",
                "reason is required.",
            )
        _validate_confidence(item.get("confidence"), issues, f"{path}.confidence")
        _validate_evidence_refs(
            item.get("evidence_refs"),
            allowed_evidence,
            issues,
            f"{path}.evidence_refs",
            required=True,
        )


def _validate_output_findings(
    value: Any,
    *,
    allowed_entries: frozenset[str],
    allowed_evidence: frozenset[str],
    issues: list[ChunkedGlossaryEditorValidationIssue],
) -> None:
    if not isinstance(value, list):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
            "findings",
            "findings must be a list.",
        )
        return
    finding_ids: set[str] = set()
    for index, item in enumerate(value):
        path = f"findings[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                path,
                "finding must be an object.",
            )
            continue
        _validate_keys(item, _FINDING_KEYS, issues, path)
        if not _non_empty_text(item.get("finding_id")):
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                f"{path}.finding_id",
                "finding_id is required.",
            )
        elif str(item["finding_id"]) in finding_ids:
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.DUPLICATE_ID,
                f"{path}.finding_id",
                "finding_id must be unique within findings.",
            )
        else:
            finding_ids.add(str(item["finding_id"]))
        if not _non_empty_text(item.get("kind")):
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                f"{path}.kind",
                "kind is required.",
            )
        _validate_enum(
            item.get("severity"),
            ChunkedGlossaryEditorFindingSeverity,
            issues,
            f"{path}.severity",
        )
        _validate_entry_refs(
            item.get("entry_ids"),
            allowed_entries,
            issues,
            f"{path}.entry_ids",
        )
        _validate_evidence_refs(
            item.get("evidence_refs"),
            allowed_evidence,
            issues,
            f"{path}.evidence_refs",
            required=True,
        )
        if not _non_empty_text(item.get("message")):
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                f"{path}.message",
                "message is required.",
            )


def _finding(
    *,
    code: ChunkedGlossaryEditorFindingCode,
    severity: ChunkedGlossaryEditorFindingSeverity,
    packet_ids: tuple[str, ...],
    entry_ids: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    message: str,
) -> ChunkedGlossaryEditorMergeFinding:
    payload = {
        "code": code.value,
        "severity": severity.value,
        "packet_ids": sorted(packet_ids),
        "entry_ids": sorted(entry_ids),
        "evidence_refs": sorted(evidence_refs),
        "message": message,
    }
    return ChunkedGlossaryEditorMergeFinding(
        finding_id=f"chunked-glossary-editor-finding:v1:{_payload_digest(payload)}",
        code=code,
        severity=severity,
        packet_ids=tuple(sorted(packet_ids)),
        entry_ids=tuple(sorted(entry_ids)),
        evidence_refs=tuple(sorted(evidence_refs)),
        message=message,
    )


def _winner_entry(entries: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return sorted(
        entries,
        key=lambda entry: (
            -float(entry["confidence"]),
            str(entry["entry_id"]),
            _payload_digest(_entry_candidate_payload(entry)),
        ),
    )[0]


def _sequence_values_conflict(
    entries: Sequence[Mapping[str, Any]],
    field: str,
) -> bool:
    values = {_normalized_text_tuple(entry.get(field)) for entry in entries}
    return len(values) > 1


def _target_values_conflict(entries: Sequence[Mapping[str, Any]]) -> bool:
    values = {
        (
            _optional_text(entry.get("target_canonical")),
            _normalized_text_tuple(entry.get("target_variants")),
            _normalized_text_tuple(entry.get("forbidden_variants")),
        )
        for entry in entries
    }
    return len(values) > 1


def _semantic_review_required(entry: Mapping[str, Any]) -> bool:
    return str(entry.get("grammatical_gender")) not in {
        GlossaryGender.UNKNOWN.value,
        GlossaryGender.NOT_APPLICABLE.value,
    }


def _merge_has_entry_blocker(
    findings: Sequence[ChunkedGlossaryEditorMergeFinding],
    entry_id: str,
) -> bool:
    return any(
        finding.severity is ChunkedGlossaryEditorFindingSeverity.BLOCKER
        and entry_id in finding.entry_ids
        for finding in findings
    )


def _entry_candidate_payload(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": str(entry["entry_id"]),
        "category": str(entry["category"]),
        "layer": str(entry["layer"]),
        "status": str(entry["status"]),
        "aliases": list(_normalized_text_tuple(entry.get("aliases"))),
        "target_canonical": _optional_text(entry.get("target_canonical")),
        "target_variants": list(_normalized_text_tuple(entry.get("target_variants"))),
        "forbidden_variants": list(
            _normalized_text_tuple(entry.get("forbidden_variants"))
        ),
        "strategy": str(entry["strategy"]),
        "grammatical_gender": str(entry["grammatical_gender"]),
        "confidence": _confidence_signature_value(entry["confidence"]),
        "evidence_refs": sorted(str(ref) for ref in entry.get("evidence_refs", ())),
    }


def _entry_proposal_payload(
    entry: ChunkedGlossaryEditorEntryProposal,
) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "packet_ids": list(entry.packet_ids),
        "evidence_refs": list(entry.evidence_refs),
        "category": entry.category,
        "layer": entry.layer,
        "status": entry.status,
        "aliases": list(entry.aliases),
        "target_canonical": entry.target_canonical,
        "target_variants": list(entry.target_variants),
        "forbidden_variants": list(entry.forbidden_variants),
        "strategy": entry.strategy,
        "grammatical_gender": entry.grammatical_gender,
        "confidence": _confidence_signature_value(entry.confidence),
        "needs_review": entry.needs_review,
    }


def _merge_finding_payload(
    finding: ChunkedGlossaryEditorMergeFinding,
) -> dict[str, Any]:
    return {
        "finding_id": finding.finding_id,
        "code": finding.code.value,
        "severity": finding.severity.value,
        "packet_ids": list(finding.packet_ids),
        "entry_ids": list(finding.entry_ids),
        "evidence_refs": list(finding.evidence_refs),
        "message": finding.message,
    }


def _merge_finding_sort_key(
    finding: ChunkedGlossaryEditorMergeFinding,
) -> tuple[str, str, str]:
    return (finding.severity.value, finding.code.value, finding.finding_id)


def _load_json_document(
    raw_json: str,
    issues: list[ChunkedGlossaryEditorValidationIssue],
) -> Mapping[str, Any] | None:
    try:
        document = json.loads(raw_json, object_pairs_hook=json_object_without_duplicate_keys)
    except DuplicateJsonKeyError as exc:
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.DUPLICATE_ID,
            "$",
            str(exc),
        )
        return None
    except json.JSONDecodeError as exc:
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.INVALID_JSON,
            "$",
            f"invalid JSON: {exc.msg}.",
        )
        return None
    if not isinstance(document, dict):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.WRONG_ROOT,
            "$",
            "chunked glossary editor output must be a JSON object.",
        )
        return None
    return document


def _validate_keys(
    value: Mapping[str, Any],
    allowed_keys: set[str],
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str,
) -> None:
    for key in sorted(set(value) - allowed_keys):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.UNEXPECTED_KEY,
            f"{path}.{key}",
            f"{key} is not allowed.",
        )


def _validate_entry_ref(
    value: Any,
    allowed_entries: frozenset[str],
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str,
) -> str | None:
    if not _non_empty_text(value):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
            path,
            "entry reference is required.",
        )
        return None
    text = str(value)
    if text not in allowed_entries:
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.INVALID_ENTRY_REF,
            path,
            f"entry reference {text!r} is not allowed for this packet.",
        )
        return None
    return text


def _validate_entry_refs(
    value: Any,
    allowed_entries: frozenset[str],
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str,
) -> tuple[str, ...]:
    refs = _validate_text_sequence(value, issues, path)
    for ref in refs:
        if ref not in allowed_entries:
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.INVALID_ENTRY_REF,
                path,
                f"entry reference {ref!r} is not allowed for this packet.",
            )
    return refs


def _validate_evidence_refs(
    value: Any,
    allowed_evidence: frozenset[str],
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    refs = _validate_text_sequence(value, issues, path)
    if required and not refs:
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.MISSING_EVIDENCE,
            path,
            "at least one evidence reference is required.",
        )
    for ref in refs:
        if ref not in allowed_evidence:
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_EVIDENCE,
                path,
                f"evidence reference {ref!r} is not allowed for this packet.",
            )
    return refs


def _validate_enum(
    value: Any,
    enum_type: type[StrEnum],
    issues: list[ChunkedGlossaryEditorValidationIssue],
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
        ChunkedGlossaryEditorValidationCode.INVALID_ENUM,
        path,
        f"{path} must be one of: {', '.join(item.value for item in enum_type)}.",
    )
    return None


def _validate_confidence(
    value: Any,
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str,
) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0.0
        or float(value) > 1.0
    ):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.INVALID_CONFIDENCE,
            path,
            "confidence must be a finite number from 0.0 through 1.0.",
        )


def _validate_optional_text(
    value: Any,
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str,
) -> None:
    if value is not None and not _non_empty_text(value):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
            path,
            f"{path} must be a non-empty string or null.",
        )


def _validate_text_sequence(
    value: Any,
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        _add_issue(
            issues,
            ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
            path,
            f"{path} must be a list.",
        )
        return ()
    items: list[str] = []
    for index, item in enumerate(value):
        if not _non_empty_text(item):
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.MISSING_FIELD,
                f"{path}[{index}]",
                "list items must be non-empty strings.",
            )
        else:
            items.append(str(item))
    return tuple(items)


def _validate_no_forbidden_raw_text_keys(
    value: Any,
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str = "$",
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _FORBIDDEN_RAW_TEXT_KEYS:
                _add_issue(
                    issues,
                    ChunkedGlossaryEditorValidationCode.UNSAFE_MODEL_OUTPUT,
                    child_path,
                    f"{key} is not allowed in chunked glossary editor output.",
                )
            _validate_no_forbidden_raw_text_keys(child, issues, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_forbidden_raw_text_keys(child, issues, f"{path}[{index}]")


def _validate_safe_strings(
    value: Any,
    issues: list[ChunkedGlossaryEditorValidationIssue],
    path: str = "$",
) -> None:
    if isinstance(value, str):
        safety = validate_model_output_safety(value)
        if safety.reason is not None:
            _add_issue(
                issues,
                ChunkedGlossaryEditorValidationCode.UNSAFE_MODEL_OUTPUT,
                path,
                f"unsafe model output: {safety.reason.value}.",
            )
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _validate_safe_strings(child, issues, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_safe_strings(child, issues, f"{path}[{index}]")


def _normalized_text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted(str(item) for item in value if _non_empty_text(item)))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _confidence_signature_value(value: Any) -> float:
    return round(float(value), 4)


def _add_issue(
    issues: list[ChunkedGlossaryEditorValidationIssue],
    code: ChunkedGlossaryEditorValidationCode,
    path: str,
    message: str,
) -> None:
    issues.append(ChunkedGlossaryEditorValidationIssue(code, path, message))


def _payload_digest(payload: Mapping[str, Any] | Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
