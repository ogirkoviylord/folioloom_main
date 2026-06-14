from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.book_profile import BookProfileKind, BookRegister
from translator_service.glossary_contracts import (
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryGender,
    GlossaryLayer,
    GlossaryStrategy,
)
from translator_service.json_utils import (
    DuplicateJsonKeyError,
    json_object_without_duplicate_keys,
)
from translator_service.model_output_safety import validate_model_output_safety

GLOSSARY_ROLE_OUTPUT_SCHEMA_VERSION = "glossary-role-output-v1"
DEFAULT_MAX_GLOSSARY_ROLE_OUTPUT_BYTES = 32_000


class GlossaryRoleId(StrEnum):
    PRO_BOOK_PROFILE_ADVISOR = "pro_book_profile_advisor"
    PRO_GLOSSARY_EDITOR_NORMALIZER = "pro_glossary_editor_normalizer"
    PRO_ENTITY_RESOLUTION_ADJUDICATOR = "pro_entity_resolution_adjudicator"
    CONTRADICTION_AND_DISAGREEMENT_CHECKER = (
        "contradiction_and_disagreement_checker"
    )


class GlossaryRoleOutputStatus(StrEnum):
    ACCEPTED = "accepted"
    ACCEPTED_LOW_CONFIDENCE = "accepted_low_confidence"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    DOWNGRADED = "downgraded"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    FAILED = "failed"


class GlossaryRoleRelationship(StrEnum):
    SAME = "same"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


class GlossaryRoleFindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class GlossaryRoleValidationCode(StrEnum):
    INVALID_JSON = "invalid_json"
    WRONG_ROOT = "wrong_root"
    UNEXPECTED_KEY = "unexpected_key"
    MISSING_FIELD = "missing_field"
    INVALID_SCHEMA_VERSION = "invalid_schema_version"
    INVALID_ENUM = "invalid_enum"
    INVALID_CONFIDENCE = "invalid_confidence"
    OVERSIZED_PAYLOAD = "oversized_payload"
    MISSING_EVIDENCE = "missing_evidence"
    DUPLICATE_ID = "duplicate_id"
    INVALID_REFERENCE = "invalid_reference"
    UNSUPPORTED_SNAPSHOT_EFFECT = "unsupported_snapshot_effect"
    UNSUPPORTED_HARD_PROMOTION = "unsupported_hard_promotion"
    UNSAFE_MODEL_OUTPUT = "unsafe_model_output"
    CONTRADICTION = "contradiction"
    DISAGREEMENT = "disagreement"


@dataclass(frozen=True)
class GlossaryRoleValidationIssue:
    code: GlossaryRoleValidationCode
    path: str
    message: str


@dataclass(frozen=True)
class GlossaryRoleValidationResult:
    issues: tuple[GlossaryRoleValidationIssue, ...] = ()
    role_id: GlossaryRoleId | None = None
    status: GlossaryRoleOutputStatus | None = None
    document: Mapping[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.issues


_ROOT_KEYS = {
    "output_schema_version",
    "role_id",
    "role_version",
    "status",
    "diagnostics_ref",
    "input_snapshot_ids",
    "evidence_packet_ids",
    "may_affect_translation_snapshot",
    "confidence",
    "evidence_refs",
    "payload",
}

_SNAPSHOT_AFFECTING_ROLE_IDS = frozenset(
    {
        GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER,
        GlossaryRoleId.CONTRADICTION_AND_DISAGREEMENT_CHECKER,
    }
)

_FORBIDDEN_RAW_TEXT_KEYS = {
    "raw_excerpt",
    "raw_text",
    "source_text",
    "prompt",
    "provider_request",
    "provider_response",
}


def validate_glossary_role_output(
    raw_json: str,
    *,
    allowed_evidence_ids: Iterable[str],
    allowed_entry_ids: Iterable[str] = (),
    max_bytes: int = DEFAULT_MAX_GLOSSARY_ROLE_OUTPUT_BYTES,
) -> GlossaryRoleValidationResult:
    issues: list[GlossaryRoleValidationIssue] = []
    allowed_evidence = frozenset(str(item) for item in allowed_evidence_ids)
    allowed_entries = frozenset(str(item) for item in allowed_entry_ids)

    if len(raw_json.encode("utf-8")) > max_bytes:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.OVERSIZED_PAYLOAD,
            "$",
            f"role output must not exceed {max_bytes} bytes.",
        )
        return GlossaryRoleValidationResult(issues=tuple(issues))

    document = _load_json_document(raw_json, issues)
    if document is None:
        return GlossaryRoleValidationResult(issues=tuple(issues))

    _validate_keys(document, _ROOT_KEYS, issues, "$")
    for key in _ROOT_KEYS:
        if key not in document:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                key,
                f"{key} is required.",
            )

    if document.get("output_schema_version") != GLOSSARY_ROLE_OUTPUT_SCHEMA_VERSION:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.INVALID_SCHEMA_VERSION,
            "output_schema_version",
            "output_schema_version must be "
            f"{GLOSSARY_ROLE_OUTPUT_SCHEMA_VERSION}.",
        )
    role_id = _validate_enum(
        document.get("role_id"),
        GlossaryRoleId,
        issues,
        "role_id",
    )
    status = _validate_enum(
        document.get("status"),
        GlossaryRoleOutputStatus,
        issues,
        "status",
    )
    if not _non_empty_text(document.get("role_version")):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "role_version",
            "role_version is required.",
        )
    if not _non_empty_text(document.get("diagnostics_ref")):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "diagnostics_ref",
            "diagnostics_ref is required.",
        )
    _validate_text_sequence(
        document.get("input_snapshot_ids"),
        issues,
        "input_snapshot_ids",
        required=True,
    )
    _validate_text_sequence(
        document.get("evidence_packet_ids"),
        issues,
        "evidence_packet_ids",
        required=True,
    )
    if not isinstance(document.get("may_affect_translation_snapshot"), bool):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "may_affect_translation_snapshot",
            "may_affect_translation_snapshot must be a boolean.",
        )
    else:
        _validate_snapshot_effect_claim(
            role_id,
            bool(document["may_affect_translation_snapshot"]),
            issues,
        )
    _validate_confidence(document.get("confidence"), issues, "confidence")
    _validate_evidence_refs(
        document.get("evidence_refs"),
        allowed_evidence,
        issues,
        "evidence_refs",
        required=True,
    )

    payload = document.get("payload")
    if not isinstance(payload, dict):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "payload",
            "payload must be an object.",
        )
    elif role_id is not None:
        _validate_payload(
            role_id,
            payload,
            allowed_evidence=allowed_evidence,
            allowed_entries=allowed_entries,
            issues=issues,
        )

    _validate_no_forbidden_raw_text_keys(document, issues)
    _validate_safe_strings(document, issues)
    return GlossaryRoleValidationResult(
        issues=tuple(issues),
        role_id=role_id,
        status=status,
        document=document if not issues else None,
    )


def validate_glossary_role_output_set(
    raw_outputs: Sequence[str],
    *,
    allowed_evidence_ids: Iterable[str],
    allowed_entry_ids: Iterable[str] = (),
    max_bytes: int = DEFAULT_MAX_GLOSSARY_ROLE_OUTPUT_BYTES,
) -> GlossaryRoleValidationResult:
    issues: list[GlossaryRoleValidationIssue] = []
    valid_documents: list[Mapping[str, Any]] = []
    seen_roles: set[GlossaryRoleId] = set()

    for index, raw_output in enumerate(raw_outputs):
        result = validate_glossary_role_output(
            raw_output,
            allowed_evidence_ids=allowed_evidence_ids,
            allowed_entry_ids=allowed_entry_ids,
            max_bytes=max_bytes,
        )
        issues.extend(_prefixed_issues(result.issues, f"outputs[{index}]"))
        if result.role_id in seen_roles:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.DUPLICATE_ID,
                f"outputs[{index}].role_id",
                "role_id must be unique in one validation set.",
            )
        if result.role_id is not None:
            seen_roles.add(result.role_id)
        if result.valid and result.document is not None:
            valid_documents.append(result.document)

    _validate_cross_role_profile_agreement(valid_documents, issues)
    return GlossaryRoleValidationResult(issues=tuple(issues))


def _validate_payload(
    role_id: GlossaryRoleId,
    payload: Mapping[str, Any],
    *,
    allowed_evidence: frozenset[str],
    allowed_entries: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    if role_id is GlossaryRoleId.PRO_BOOK_PROFILE_ADVISOR:
        _validate_profile_advisor_payload(payload, allowed_evidence, issues)
    elif role_id is GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER:
        _validate_glossary_editor_payload(payload, allowed_evidence, issues)
    elif role_id is GlossaryRoleId.PRO_ENTITY_RESOLUTION_ADJUDICATOR:
        _validate_entity_resolution_payload(
            payload,
            allowed_evidence,
            allowed_entries,
            issues,
        )
    elif role_id is GlossaryRoleId.CONTRADICTION_AND_DISAGREEMENT_CHECKER:
        _validate_contradiction_payload(
            payload,
            allowed_evidence,
            allowed_entries,
            issues,
        )


def _validate_profile_advisor_payload(
    payload: Mapping[str, Any],
    allowed_evidence: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    _validate_keys(
        payload,
        {"profile_advice", "warnings", "mixed_section_notes"},
        issues,
        "payload",
    )
    advice = payload.get("profile_advice")
    if not isinstance(advice, dict):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "payload.profile_advice",
            "profile_advice must be an object.",
        )
        return
    _validate_keys(
        advice,
        {
            "primary_profile",
            "secondary_profiles",
            "register",
            "domain_hints",
            "confidence",
            "evidence_refs",
        },
        issues,
        "payload.profile_advice",
    )
    _validate_enum(
        advice.get("primary_profile"),
        BookProfileKind,
        issues,
        "payload.profile_advice.primary_profile",
    )
    _validate_enum_sequence(
        advice.get("secondary_profiles"),
        BookProfileKind,
        issues,
        "payload.profile_advice.secondary_profiles",
        required=False,
    )
    _validate_enum(
        advice.get("register"),
        BookRegister,
        issues,
        "payload.profile_advice.register",
    )
    _validate_text_sequence(
        advice.get("domain_hints"),
        issues,
        "payload.profile_advice.domain_hints",
        required=False,
    )
    _validate_confidence(
        advice.get("confidence"),
        issues,
        "payload.profile_advice.confidence",
    )
    _validate_evidence_refs(
        advice.get("evidence_refs"),
        allowed_evidence,
        issues,
        "payload.profile_advice.evidence_refs",
        required=True,
    )
    _validate_notes(
        payload.get("warnings"),
        allowed_evidence,
        issues,
        "payload.warnings",
    )
    _validate_notes(
        payload.get("mixed_section_notes"),
        allowed_evidence,
        issues,
        "payload.mixed_section_notes",
    )


def _validate_glossary_editor_payload(
    payload: Mapping[str, Any],
    allowed_evidence: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    _validate_keys(
        payload,
        {"profile_context", "entries", "rejected_candidates"},
        issues,
        "payload",
    )
    profile_context = payload.get("profile_context")
    if profile_context is not None:
        if not isinstance(profile_context, dict):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                "payload.profile_context",
                "profile_context must be an object when present.",
            )
        else:
            _validate_keys(
                profile_context,
                {"primary_profile", "profile_id"},
                issues,
                "payload.profile_context",
            )
            _validate_enum(
                profile_context.get("primary_profile"),
                BookProfileKind,
                issues,
                "payload.profile_context.primary_profile",
            )
            if not _non_empty_text(profile_context.get("profile_id")):
                _add_issue(
                    issues,
                    GlossaryRoleValidationCode.MISSING_FIELD,
                    "payload.profile_context.profile_id",
                    "profile_id is required.",
                )
    entries = payload.get("entries")
    if not isinstance(entries, list):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "payload.entries",
            "entries must be a list.",
        )
    else:
        _validate_glossary_entries(entries, allowed_evidence, issues)
    _validate_rejected_candidates(
        payload.get("rejected_candidates"),
        allowed_evidence,
        issues,
    )


def _validate_glossary_entries(
    entries: Sequence[Any],
    allowed_evidence: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    entry_ids: set[str] = set()
    for index, item in enumerate(entries):
        path = f"payload.entries[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                path,
                "entry must be an object.",
            )
            continue
        _validate_keys(
            item,
            {
                "entry_id",
                "category",
                "layer",
                "status",
                "source_canonical",
                "aliases",
                "target_canonical",
                "target_variants",
                "forbidden_variants",
                "strategy",
                "grammatical_gender",
                "confidence",
                "evidence_refs",
                "profile_rule_ids",
            },
            issues,
            path,
        )
        entry_id = item.get("entry_id")
        if not _non_empty_text(entry_id):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                f"{path}.entry_id",
                "entry_id is required.",
            )
        elif entry_id in entry_ids:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.DUPLICATE_ID,
                f"{path}.entry_id",
                "entry_id must be unique.",
            )
        else:
            entry_ids.add(str(entry_id))
        _validate_enum(
            item.get("category"),
            GlossaryEntryCategory,
            issues,
            f"{path}.category",
        )
        layer = _validate_enum(
            item.get("layer"),
            GlossaryLayer,
            issues,
            f"{path}.layer",
        )
        status = _validate_enum(
            item.get("status"),
            GlossaryEntryStatus,
            issues,
            f"{path}.status",
        )
        _validate_enum(
            item.get("strategy"),
            GlossaryStrategy,
            issues,
            f"{path}.strategy",
        )
        _validate_enum(
            item.get("grammatical_gender"),
            GlossaryGender,
            issues,
            f"{path}.grammatical_gender",
        )
        if layer is GlossaryLayer.HARD:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.UNSUPPORTED_HARD_PROMOTION,
                f"{path}.layer",
                "DeepSeek role output cannot promote glossary entries to hard.",
            )
        if (
            status is GlossaryEntryStatus.REJECTED
            and layer is not GlossaryLayer.DIAGNOSTIC
        ):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.INVALID_ENUM,
                f"{path}.status",
                "rejected entries must remain diagnostic.",
            )
        if not _non_empty_text(item.get("source_canonical")):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                f"{path}.source_canonical",
                "source_canonical is required.",
            )
        _validate_optional_text(
            item.get("target_canonical"),
            issues,
            f"{path}.target_canonical",
        )
        _validate_text_sequence(
            item.get("aliases"),
            issues,
            f"{path}.aliases",
            required=False,
        )
        _validate_text_sequence(
            item.get("target_variants"),
            issues,
            f"{path}.target_variants",
            required=False,
        )
        _validate_text_sequence(
            item.get("forbidden_variants"),
            issues,
            f"{path}.forbidden_variants",
            required=False,
        )
        _validate_text_sequence(
            item.get("profile_rule_ids"),
            issues,
            f"{path}.profile_rule_ids",
            required=False,
        )
        _validate_confidence(item.get("confidence"), issues, f"{path}.confidence")
        _validate_evidence_refs(
            item.get("evidence_refs"),
            allowed_evidence,
            issues,
            f"{path}.evidence_refs",
            required=True,
        )


def _validate_rejected_candidates(
    rejected_candidates: Any,
    allowed_evidence: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    if rejected_candidates is None:
        return
    if not isinstance(rejected_candidates, list):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "payload.rejected_candidates",
            "rejected_candidates must be a list when present.",
        )
        return
    for index, item in enumerate(rejected_candidates):
        path = f"payload.rejected_candidates[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                path,
                "rejected candidate must be an object.",
            )
            continue
        _validate_keys(
            item,
            {"candidate_id", "reason", "evidence_refs"},
            issues,
            path,
        )
        if not _non_empty_text(item.get("candidate_id")):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                f"{path}.candidate_id",
                "candidate_id is required.",
            )
        if not _non_empty_text(item.get("reason")):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                f"{path}.reason",
                "reason is required.",
            )
        _validate_evidence_refs(
            item.get("evidence_refs"),
            allowed_evidence,
            issues,
            f"{path}.evidence_refs",
            required=True,
        )


def _validate_entity_resolution_payload(
    payload: Mapping[str, Any],
    allowed_evidence: frozenset[str],
    allowed_entries: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    _validate_keys(payload, {"relationships"}, issues, "payload")
    relationships = payload.get("relationships")
    if not isinstance(relationships, list):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "payload.relationships",
            "relationships must be a list.",
        )
        return
    relationship_ids: set[str] = set()
    for index, item in enumerate(relationships):
        path = f"payload.relationships[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                path,
                "relationship must be an object.",
            )
            continue
        _validate_keys(
            item,
            {
                "relationship_id",
                "left_entry_id",
                "right_entry_id",
                "relationship",
                "confidence",
                "evidence_refs",
            },
            issues,
            path,
        )
        _validate_unique_text_id(
            item.get("relationship_id"),
            relationship_ids,
            issues,
            f"{path}.relationship_id",
        )
        _validate_entry_ref(
            item.get("left_entry_id"),
            allowed_entries,
            issues,
            f"{path}.left_entry_id",
        )
        _validate_entry_ref(
            item.get("right_entry_id"),
            allowed_entries,
            issues,
            f"{path}.right_entry_id",
        )
        _validate_enum(
            item.get("relationship"),
            GlossaryRoleRelationship,
            issues,
            f"{path}.relationship",
        )
        _validate_confidence(item.get("confidence"), issues, f"{path}.confidence")
        _validate_evidence_refs(
            item.get("evidence_refs"),
            allowed_evidence,
            issues,
            f"{path}.evidence_refs",
            required=True,
        )


def _validate_contradiction_payload(
    payload: Mapping[str, Any],
    allowed_evidence: frozenset[str],
    allowed_entries: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    _validate_keys(payload, {"findings"}, issues, "payload")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            "payload.findings",
            "findings must be a list.",
        )
        return
    finding_ids: set[str] = set()
    for index, item in enumerate(findings):
        path = f"payload.findings[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                path,
                "finding must be an object.",
            )
            continue
        _validate_keys(
            item,
            {
                "finding_id",
                "finding_type",
                "severity",
                "role_ids",
                "entry_ids",
                "evidence_refs",
                "message",
            },
            issues,
            path,
        )
        _validate_unique_text_id(
            item.get("finding_id"),
            finding_ids,
            issues,
            f"{path}.finding_id",
        )
        finding_type = item.get("finding_type")
        if finding_type not in {"contradiction", "role_disagreement"}:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.INVALID_ENUM,
                f"{path}.finding_type",
                "finding_type must be contradiction or role_disagreement.",
            )
        severity = _validate_enum(
            item.get("severity"),
            GlossaryRoleFindingSeverity,
            issues,
            f"{path}.severity",
        )
        _validate_enum_sequence(
            item.get("role_ids"),
            GlossaryRoleId,
            issues,
            f"{path}.role_ids",
            required=True,
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
                GlossaryRoleValidationCode.MISSING_FIELD,
                f"{path}.message",
                "message is required.",
            )
        if severity is GlossaryRoleFindingSeverity.BLOCKER:
            code = (
                GlossaryRoleValidationCode.CONTRADICTION
                if finding_type == "contradiction"
                else GlossaryRoleValidationCode.DISAGREEMENT
            )
            _add_issue(
                issues,
                code,
                path,
                "blocking contradiction/disagreement cannot be promoted.",
            )


def _validate_cross_role_profile_agreement(
    documents: Sequence[Mapping[str, Any]],
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    advisor_profile: str | None = None
    editor_profile: str | None = None
    for document in documents:
        payload = document.get("payload")
        if not isinstance(payload, dict):
            continue
        if document.get("role_id") == GlossaryRoleId.PRO_BOOK_PROFILE_ADVISOR.value:
            advice = payload.get("profile_advice")
            if isinstance(advice, dict) and isinstance(
                advice.get("primary_profile"),
                str,
            ):
                advisor_profile = advice["primary_profile"]
        if (
            document.get("role_id")
            == GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER.value
        ):
            context = payload.get("profile_context")
            if isinstance(context, dict) and isinstance(
                context.get("primary_profile"),
                str,
            ):
                editor_profile = context["primary_profile"]
    if advisor_profile and editor_profile and advisor_profile != editor_profile:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.DISAGREEMENT,
            "outputs.profile_context.primary_profile",
            "profile advisor and glossary editor primary_profile disagree.",
        )


def _validate_snapshot_effect_claim(
    role_id: GlossaryRoleId | None,
    may_affect_translation_snapshot: bool,
    issues: list[GlossaryRoleValidationIssue],
) -> None:
    if (
        role_id is not None
        and may_affect_translation_snapshot
        and role_id not in _SNAPSHOT_AFFECTING_ROLE_IDS
    ):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.UNSUPPORTED_SNAPSHOT_EFFECT,
            "may_affect_translation_snapshot",
            f"{role_id.value} cannot directly affect translation_snapshot.",
        )


def _validate_notes(
    notes: Any,
    allowed_evidence: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
    path: str,
) -> None:
    if notes is None:
        return
    if not isinstance(notes, list):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            path,
            f"{path} must be a list when present.",
        )
        return
    for index, item in enumerate(notes):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                item_path,
                "note must be an object.",
            )
            continue
        _validate_keys(
            item,
            {"note_id", "kind", "severity", "message", "evidence_refs"},
            issues,
            item_path,
        )
        if not _non_empty_text(item.get("note_id")):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                f"{item_path}.note_id",
                "note_id is required.",
            )
        if not _non_empty_text(item.get("kind")):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                f"{item_path}.kind",
                "kind is required.",
            )
        _validate_enum(
            item.get("severity"),
            GlossaryRoleFindingSeverity,
            issues,
            f"{item_path}.severity",
        )
        if not _non_empty_text(item.get("message")):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                f"{item_path}.message",
                "message is required.",
            )
        _validate_evidence_refs(
            item.get("evidence_refs"),
            allowed_evidence,
            issues,
            f"{item_path}.evidence_refs",
            required=True,
        )


def _validate_safe_strings(
    value: Any,
    issues: list[GlossaryRoleValidationIssue],
    path: str = "$",
) -> None:
    if isinstance(value, str):
        safety = validate_model_output_safety(value)
        if safety.reason is not None:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.UNSAFE_MODEL_OUTPUT,
                path,
                f"unsafe model output: {safety.reason.value}.",
            )
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _validate_safe_strings(child, issues, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_safe_strings(child, issues, f"{path}[{index}]")


def _validate_no_forbidden_raw_text_keys(
    value: Any,
    issues: list[GlossaryRoleValidationIssue],
    path: str = "$",
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _FORBIDDEN_RAW_TEXT_KEYS:
                _add_issue(
                    issues,
                    GlossaryRoleValidationCode.UNSAFE_MODEL_OUTPUT,
                    child_path,
                    f"{key} is not allowed in role contract output.",
                )
            _validate_no_forbidden_raw_text_keys(child, issues, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_forbidden_raw_text_keys(child, issues, f"{path}[{index}]")


def _validate_keys(
    value: Mapping[str, Any],
    allowed_keys: set[str],
    issues: list[GlossaryRoleValidationIssue],
    path: str,
) -> None:
    unexpected = sorted(set(value) - allowed_keys)
    for key in unexpected:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.UNEXPECTED_KEY,
            f"{path}.{key}",
            f"{key} is not allowed.",
        )


def _validate_evidence_refs(
    value: Any,
    allowed_evidence: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
    path: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    refs = _validate_text_sequence(value, issues, path, required=required)
    for ref in refs:
        if ref not in allowed_evidence:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_EVIDENCE,
                path,
                f"evidence reference {ref!r} is not defined.",
            )
    return refs


def _validate_entry_refs(
    value: Any,
    allowed_entries: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
    path: str,
) -> tuple[str, ...]:
    refs = _validate_text_sequence(value, issues, path, required=False)
    for ref in refs:
        if allowed_entries and ref not in allowed_entries:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.INVALID_REFERENCE,
                path,
                f"entry reference {ref!r} is not defined.",
            )
    return refs


def _validate_entry_ref(
    value: Any,
    allowed_entries: frozenset[str],
    issues: list[GlossaryRoleValidationIssue],
    path: str,
) -> None:
    if not _non_empty_text(value):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            path,
            "entry reference is required.",
        )
    elif allowed_entries and str(value) not in allowed_entries:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.INVALID_REFERENCE,
            path,
            f"entry reference {value!r} is not defined.",
        )


def _validate_text_sequence(
    value: Any,
    issues: list[GlossaryRoleValidationIssue],
    path: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            path,
            f"{path} must be a list.",
        )
        return ()
    if required and not value:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            path,
            f"{path} must not be empty.",
        )
    parsed: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not _non_empty_text(item):
            _add_issue(
                issues,
                GlossaryRoleValidationCode.MISSING_FIELD,
                item_path,
                "value must be a non-empty string.",
            )
            continue
        text = str(item)
        if text in seen:
            _add_issue(
                issues,
                GlossaryRoleValidationCode.DUPLICATE_ID,
                item_path,
                "values must be unique.",
            )
        seen.add(text)
        parsed.append(text)
    return tuple(parsed)


def _validate_enum_sequence(
    value: Any,
    enum_type: type[StrEnum],
    issues: list[GlossaryRoleValidationIssue],
    path: str,
    *,
    required: bool,
) -> None:
    values = _validate_text_sequence(value, issues, path, required=required)
    for index, item in enumerate(values):
        _validate_enum(item, enum_type, issues, f"{path}[{index}]")


def _validate_unique_text_id(
    value: Any,
    seen: set[str],
    issues: list[GlossaryRoleValidationIssue],
    path: str,
) -> None:
    if not _non_empty_text(value):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            path,
            "id is required.",
        )
        return
    text = str(value)
    if text in seen:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.DUPLICATE_ID,
            path,
            "id must be unique.",
        )
    seen.add(text)


def _validate_optional_text(
    value: Any,
    issues: list[GlossaryRoleValidationIssue],
    path: str,
) -> None:
    if value is not None and not _non_empty_text(value):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.MISSING_FIELD,
            path,
            "value must be null or a non-empty string.",
        )


def _validate_confidence(
    value: Any,
    issues: list[GlossaryRoleValidationIssue],
    path: str,
) -> None:
    if not _valid_confidence(value):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.INVALID_CONFIDENCE,
            path,
            "confidence must be a finite number from 0.0 through 1.0.",
        )


def _validate_enum(
    value: Any,
    enum_type: type[StrEnum],
    issues: list[GlossaryRoleValidationIssue],
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
        GlossaryRoleValidationCode.INVALID_ENUM,
        path,
        f"{path} must be one of: {', '.join(item.value for item in enum_type)}.",
    )
    return None


def _load_json_document(
    raw_json: str,
    issues: list[GlossaryRoleValidationIssue],
) -> Mapping[str, Any] | None:
    try:
        document = json.loads(
            raw_json,
            object_pairs_hook=json_object_without_duplicate_keys,
        )
    except DuplicateJsonKeyError as exc:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.UNEXPECTED_KEY,
            "$",
            str(exc),
        )
        return None
    except json.JSONDecodeError:
        _add_issue(
            issues,
            GlossaryRoleValidationCode.INVALID_JSON,
            "$",
            "role output must be valid JSON.",
        )
        return None
    if not isinstance(document, dict):
        _add_issue(
            issues,
            GlossaryRoleValidationCode.WRONG_ROOT,
            "$",
            "role output root must be an object.",
        )
        return None
    return document


def _prefixed_issues(
    issues: tuple[GlossaryRoleValidationIssue, ...],
    prefix: str,
) -> tuple[GlossaryRoleValidationIssue, ...]:
    return tuple(
        GlossaryRoleValidationIssue(
            code=issue.code,
            path=f"{prefix}.{issue.path}",
            message=issue.message,
        )
        for issue in issues
    )


def _add_issue(
    issues: list[GlossaryRoleValidationIssue],
    code: GlossaryRoleValidationCode,
    path: str,
    message: str,
) -> None:
    issues.append(GlossaryRoleValidationIssue(code=code, path=path, message=message))


def _valid_confidence(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
