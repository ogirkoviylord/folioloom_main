"""Metadata-only content-role vocabulary for #781 fixture contracts.

This module intentionally defines constants and validation helpers only. It does
not annotate adapters, alter translation output, change provider/profile/cache
behavior, or approve any gate/report persistence change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

FIXTURE_SCHEMA_VERSION = "content-role-fixture-contract-v1"
ANNOTATION_SCHEMA_VERSION = "content-role-annotation-v1"

SECTION_BLOCK_ACTION_ENVELOPE = "shadow_report_translate_include"
TOKEN_ACTION_ENVELOPE = "token_preserve_only"
ALLOWED_ACTION_ENVELOPES = (
    SECTION_BLOCK_ACTION_ENVELOPE,
    TOKEN_ACTION_ENVELOPE,
)

ALLOWED_ROLES = (
    "main_content",
    "title_heading",
    "reader_navigation",
    "reader_visible_paratext",
    "legal_rights_boilerplate",
    "archive_digitization_artifact",
    "publisher_metadata",
    "unknown_paratext",
)

CONFIDENCE_LEVELS = (
    "high",
    "medium",
    "low",
    "unknown",
)

EVIDENCE_CONFIDENCE_LEVELS = (
    "strong",
    "medium",
    "weak",
    "unknown",
)

SIGNAL_FAMILIES = (
    "structural_semantic",
    "role_heading",
    "body_lexical_cluster",
    "url_or_rights_pattern",
    "path_class_id",
    "provenance_source_clue",
    "position_layout",
)

STRONG_HIGH_CONFIDENCE_FAMILIES = frozenset(
    {
        "structural_semantic",
        "body_lexical_cluster",
    }
)

FORMAT_SURFACES = (
    "epub",
    "docx",
    "txt",
    "generic_metadata",
)

SOURCE_SURFACES = (
    "epub_xhtml_body",
    "epub_opf_metadata",
    "epub_ncx_nav",
    "epub_xhtml_nav",
    "epub_xhtml_title",
    "docx_paragraph",
    "docx_header",
    "docx_footer",
    "docx_footnote",
    "docx_endnote",
    "docx_comment",
    "txt_line",
    "txt_segment",
    "unknown",
)

GRANULARITIES = (
    "section",
    "block",
    "token",
)

REPORTING_BUCKETS = (
    "main",
    "reader_visible",
    "legal_archive_shadow",
    "publisher_metadata_shadow",
    "unknown_shadow",
    "token_identifier",
)
ROLE_REPORTING_BUCKETS: Mapping[str, str] = {
    "main_content": "main",
    "title_heading": "reader_visible",
    "reader_navigation": "reader_visible",
    "reader_visible_paratext": "reader_visible",
    "legal_rights_boilerplate": "legal_archive_shadow",
    "archive_digitization_artifact": "legal_archive_shadow",
    "publisher_metadata": "publisher_metadata_shadow",
    "unknown_paratext": "unknown_shadow",
}

CONFLICT_RULES = (
    "reader_visible_wins",
    "main_content_wins",
    "downgrade_unknown",
    "publisher_metadata_separate",
    "no_conflict",
)

REQUIRED_FIXTURE_CASE_FIELDS = (
    "schema_version",
    "fixture_id",
    "format_surface",
    "source_structure",
    "text_snippet_policy",
    "expected_role",
    "expected_confidence",
    "positive_signals",
    "negative_signals",
    "conflict_rule_expected",
    "fallback_expected",
    "protected_token_expectations",
    "reporting_bucket",
    "allowed_action_envelope",
    "behavior_allowed",
    "raw_publication_allowed",
    "single_signal_shortcuts_rejected",
)

REQUIRED_SOURCE_STRUCTURE_FIELDS = (
    "surface",
    "source_path_or_chunk_id",
    "granularity",
    "structure_hints",
    "position_hint",
)

REQUIRED_TEXT_SNIPPET_POLICY_FIELDS = (
    "fixture_text_kind",
    "raw_excerpt_included",
    "private_or_copyrighted_source_allowed",
    "max_synthetic_chars_if_needed",
    "publication_rule",
)
REQUIRED_EVIDENCE_METADATA_FIELDS = (
    "signal_family",
    "strength",
    "metadata_value_kind",
    "reason_code",
)

BEHAVIOR_RISK_APPROVAL_FLAGS = (
    "output_behavior_change_approved",
    "gate_exclusion_approved",
    "provider_profile_change_approved",
    "cache_runtime_db_change_approved",
    "public_legal_wording_approved",
    "provider_full_book_run_approved",
    "deploy_release_merge_approved",
)

DISALLOWED_SINGLE_SIGNAL_SHORTCUTS = (
    "publisher_source_name_alone",
    "position_alone",
    "path_alone",
    "url_alone",
    "all_caps_alone",
    "one_broad_word",
    "cache_or_output_side_text_alone",
    "project_gutenberg_or_source_specific_key",
)

METADATA_ONLY_FORBIDDEN_FIELD_NAMES = (
    "api_key",
    "authorization",
    "auth_material",
    "owner_only_diagnostics",
    "password",
    "private_diagnostics",
    "prompt",
    "prompt_body",
    "provider_request",
    "provider_response",
    "raw_provider_response",
    "raw_source",
    "raw_target",
    "raw_translation",
    "secret",
    "source_text",
    "system_prompt",
    "translated_passage",
    "translated_text",
    "user_prompt",
)
METADATA_ONLY_FORBIDDEN_EXACT_VALUES = frozenset(
    METADATA_ONLY_FORBIDDEN_FIELD_NAMES
    + (
        "private_diagnostic",
        "provider",
        "source",
        "target",
        "translation",
    )
)
METADATA_ONLY_FORBIDDEN_VALUE_MARKERS = (
    "begin_untrusted_document_content",
    "<translation_batch",
    "api key",
    "api-key",
    "api_key",
    "apikey",
    "authorization:",
    "bearer ",
    "contains secret",
    "contains-secret",
    "owner only diagnostics",
    "owner_only_diagnostics",
    "owner_policy_tbd_later_behavior",
    "private diagnostics",
    "private_diagnostics",
    "project gutenberg",
    "prompt body",
    "prompt_body",
    "prompt excerpt",
    "raw prompt",
    "provider body",
    "provider_body",
    "provider request",
    "provider response",
    "provider_request",
    "provider_response",
    "raw provider",
    "raw_provider",
    "raw source",
    "raw_source",
    "raw target",
    "raw_target",
    "raw translation",
    "raw_translation",
    "secret material",
    "sk-",
    "source excerpt",
    "source text",
    "source_text",
    "translated passage",
    "translated text",
    "translated_passage",
    "translated_text",
    "translation excerpt",
)
MAX_METADATA_SCALAR_CHARS = 280


def _as_tuple(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        return (values,)
    return tuple(str(value) for value in values)


def _validate_metadata_scalar(field_name: str, value: str) -> str:
    normalized_field_name = field_name.strip().lower()
    if normalized_field_name in METADATA_ONLY_FORBIDDEN_FIELD_NAMES:
        raise ValueError(f"metadata field is forbidden: {field_name}")
    if "\n" in value or "\r" in value or len(value) > MAX_METADATA_SCALAR_CHARS:
        raise ValueError(f"metadata value is not PR-safe: {field_name}")
    normalized_value = value.strip().lower()
    if normalized_value in METADATA_ONLY_FORBIDDEN_EXACT_VALUES or any(
        marker in normalized_value for marker in METADATA_ONLY_FORBIDDEN_VALUE_MARKERS
    ):
        raise ValueError(f"metadata value is forbidden: {field_name}")
    return value


def reporting_bucket_for_annotation(
    *,
    role: str,
    granularity: str,
    token_kinds: Sequence[str] = (),
) -> str:
    """Return the deterministic metadata-only report bucket for an annotation.

    The bucket is descriptive only. It does not authorize omit/preserve/exclude
    behavior, provider/profile/cache/runtime changes, output changes, or gate
    pass/fail decisions.
    """

    if role not in ALLOWED_ROLES:
        raise ValueError("invalid content role")
    if granularity not in GRANULARITIES:
        raise ValueError("invalid annotation granularity")
    normalized_token_kinds = _as_tuple(token_kinds)
    for token_kind in normalized_token_kinds:
        _validate_metadata_scalar("token_kind", token_kind)
    if (
        granularity == "token"
        and role == "publisher_metadata"
        and normalized_token_kinds
    ):
        return "token_identifier"
    return ROLE_REPORTING_BUCKETS[role]


def report_bucket_metadata(
    *,
    role: str,
    granularity: str,
    token_kinds: Sequence[str] = (),
) -> dict[str, Any]:
    """Serialize a descriptive report-bucket contract as metadata only."""

    return {
        "reporting_bucket": reporting_bucket_for_annotation(
            role=role,
            granularity=granularity,
            token_kinds=token_kinds,
        ),
        "metadata_only": True,
        "behavior_allowed": False,
        "raw_publication_allowed": False,
        "risk_approval_flags": {
            flag_name: False for flag_name in BEHAVIOR_RISK_APPROVAL_FLAGS
        },
    }


@dataclass(frozen=True)
class SourceLocator:
    """Adapter-neutral source location for metadata-only role annotations."""

    surface: str
    source_path_or_chunk_id: str
    granularity: str
    structure_hints: Sequence[str] = ()
    position_hint: str = "unknown"

    def __post_init__(self) -> None:
        if self.surface not in SOURCE_SURFACES:
            raise ValueError("invalid source surface")
        if self.granularity not in GRANULARITIES:
            raise ValueError("invalid annotation granularity")
        _validate_metadata_scalar(
            "source_path_or_chunk_id",
            self.source_path_or_chunk_id,
        )
        _validate_metadata_scalar("position_hint", self.position_hint)
        object.__setattr__(self, "structure_hints", _as_tuple(self.structure_hints))
        for hint in self.structure_hints:
            _validate_metadata_scalar("structure_hint", hint)

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "source_path_or_chunk_id": self.source_path_or_chunk_id,
            "granularity": self.granularity,
            "structure_hints": list(self.structure_hints),
            "position_hint": self.position_hint,
        }


@dataclass(frozen=True)
class ContentRoleEvidence:
    """One metadata-only source-side evidence signal for a role annotation."""

    signal_family: str
    strength: str
    metadata_value_kind: str
    reason_code: str

    def __post_init__(self) -> None:
        if self.signal_family not in SIGNAL_FAMILIES:
            raise ValueError("invalid signal family")
        if self.strength not in EVIDENCE_CONFIDENCE_LEVELS:
            raise ValueError("invalid evidence strength")
        _validate_metadata_scalar("metadata_value_kind", self.metadata_value_kind)
        _validate_metadata_scalar("reason_code", self.reason_code)

    def to_metadata_dict(self) -> dict[str, str]:
        return {
            "signal_family": self.signal_family,
            "strength": self.strength,
            "metadata_value_kind": self.metadata_value_kind,
            "reason_code": self.reason_code,
        }


def source_locator_from_metadata(metadata: Mapping[str, Any]) -> SourceLocator:
    """Build a metadata-only SourceLocator from adapter-neutral fixture fields."""

    missing = [
        field for field in REQUIRED_SOURCE_STRUCTURE_FIELDS if field not in metadata
    ]
    if missing:
        raise ValueError(f"missing source locator fields: {', '.join(missing)}")
    return SourceLocator(
        surface=str(metadata["surface"]),
        source_path_or_chunk_id=str(metadata["source_path_or_chunk_id"]),
        granularity=str(metadata["granularity"]),
        structure_hints=_as_tuple(metadata["structure_hints"]),
        position_hint=str(metadata["position_hint"]),
    )


def content_role_evidence_from_metadata(
    metadata: Mapping[str, Any],
) -> ContentRoleEvidence:
    """Build one metadata-only evidence signal from deterministic fixture fields."""

    missing = [
        field for field in REQUIRED_EVIDENCE_METADATA_FIELDS if field not in metadata
    ]
    if missing:
        raise ValueError(f"missing content-role evidence fields: {', '.join(missing)}")
    return ContentRoleEvidence(
        signal_family=str(metadata["signal_family"]),
        strength=str(metadata["strength"]),
        metadata_value_kind=str(metadata["metadata_value_kind"]),
        reason_code=str(metadata["reason_code"]),
    )


@dataclass(frozen=True)
class TokenPreservationMetadata:
    """Token-scoped preservation metadata; never authorizes section behavior."""

    token_kinds: Sequence[str] = ()
    token_scope_only: bool = True
    section_omit_or_preserve_allowed: bool = False
    token_action_envelope: str = TOKEN_ACTION_ENVELOPE

    def __post_init__(self) -> None:
        if self.token_action_envelope != TOKEN_ACTION_ENVELOPE:
            raise ValueError("token preservation must use token_preserve_only")
        if self.token_scope_only is not True:
            raise ValueError("token preservation must remain token-scoped")
        if self.section_omit_or_preserve_allowed is not False:
            raise ValueError("token preservation must not authorize section behavior")
        object.__setattr__(self, "token_kinds", _as_tuple(self.token_kinds))
        for token_kind in self.token_kinds:
            _validate_metadata_scalar("token_kind", token_kind)

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "token_action_envelope": self.token_action_envelope,
            "token_scope_only": self.token_scope_only,
            "section_omit_or_preserve_allowed": self.section_omit_or_preserve_allowed,
            "token_kinds": list(self.token_kinds),
        }


@dataclass(frozen=True)
class ContentRoleAnnotation:
    """Metadata-only source-side content-role annotation carrier.

    The carrier is deliberately behavior-neutral: section/block annotations can
    only shadow-report while translating/including, and token annotations can
    only describe token-scoped preservation metadata.
    """

    locator: SourceLocator
    role: str
    confidence: str
    evidence: Sequence[ContentRoleEvidence]
    reporting_bucket: str
    allowed_action_envelope: str | None = None
    conflict_notes: Sequence[str] = ()
    token_preservation: TokenPreservationMetadata | None = None

    def __post_init__(self) -> None:
        if self.role not in ALLOWED_ROLES:
            raise ValueError("invalid content role")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError("invalid content-role confidence")
        if self.reporting_bucket not in REPORTING_BUCKETS:
            raise ValueError("invalid reporting bucket")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "conflict_notes", _as_tuple(self.conflict_notes))
        for note in self.conflict_notes:
            _validate_metadata_scalar("conflict_note", note)
        self._validate_evidence()
        self._validate_action_envelope()
        self._validate_reporting_bucket()

    def _validate_evidence(self) -> None:
        if not self.evidence:
            raise ValueError("content-role annotation requires evidence")
        families = frozenset(evidence.signal_family for evidence in self.evidence)
        if self.confidence == "high":
            has_strong_core_signal = any(
                evidence.signal_family in STRONG_HIGH_CONFIDENCE_FAMILIES
                and evidence.strength in {"strong", "medium"}
                for evidence in self.evidence
            )
            if len(families) < 2 or not has_strong_core_signal:
                raise ValueError(
                    "high confidence requires multiple independent evidence signals"
                )

    def _validate_action_envelope(self) -> None:
        expected_envelope = (
            TOKEN_ACTION_ENVELOPE
            if self.locator.granularity == "token"
            else SECTION_BLOCK_ACTION_ENVELOPE
        )
        envelope = self.allowed_action_envelope or expected_envelope
        if envelope != expected_envelope or envelope not in ALLOWED_ACTION_ENVELOPES:
            raise ValueError("behavior-changing action envelope is not allowed")
        object.__setattr__(self, "allowed_action_envelope", envelope)
        if self.locator.granularity == "token":
            token_preservation = self.token_preservation or TokenPreservationMetadata()
            object.__setattr__(self, "token_preservation", token_preservation)
        elif self.token_preservation is not None:
            raise ValueError("token preservation metadata must remain token-scoped")

    def _validate_reporting_bucket(self) -> None:
        token_kinds = (
            ()
            if self.token_preservation is None
            else self.token_preservation.token_kinds
        )
        expected_bucket = reporting_bucket_for_annotation(
            role=self.role,
            granularity=self.locator.granularity,
            token_kinds=token_kinds,
        )
        if self.reporting_bucket != expected_bucket:
            raise ValueError("reporting bucket does not match metadata-only contract")

    def to_metadata_dict(self) -> dict[str, Any]:
        metadata = {
            "schema_version": ANNOTATION_SCHEMA_VERSION,
            "locator": self.locator.to_metadata_dict(),
            "role": self.role,
            "confidence": self.confidence,
            "evidence": [evidence.to_metadata_dict() for evidence in self.evidence],
            "reporting_bucket": self.reporting_bucket,
            "allowed_action_envelope": self.allowed_action_envelope,
            "conflict_notes": list(self.conflict_notes),
            "behavior_allowed": False,
            "raw_publication_allowed": False,
            "risk_approval_flags": {
                flag_name: False for flag_name in BEHAVIOR_RISK_APPROVAL_FLAGS
            },
        }
        if self.token_preservation is not None:
            metadata["token_preservation"] = self.token_preservation.to_metadata_dict()
        return metadata


def content_role_metadata_pairs(
    annotation: ContentRoleAnnotation,
) -> tuple[tuple[str, str], ...]:
    """Flatten an annotation into PR-safe namespaced scalar metadata pairs.

    The adapter-facing representation deliberately avoids nested dict/list
    values, raw text, provider payloads, diagnostics, and behavior-enabling
    switches. It is descriptive metadata only.
    """

    pairs = (
        ("content_role.schema_version", ANNOTATION_SCHEMA_VERSION),
        ("content_role.source_surface", annotation.locator.surface),
        ("content_role.source_granularity", annotation.locator.granularity),
        ("content_role.role", annotation.role),
        ("content_role.confidence", annotation.confidence),
        ("content_role.reporting_bucket", annotation.reporting_bucket),
        (
            "content_role.allowed_action_envelope",
            str(annotation.allowed_action_envelope),
        ),
        ("content_role.behavior_allowed", "false"),
        ("content_role.raw_publication_allowed", "false"),
        ("content_role.risk_approval_flags", "all_false"),
        (
            "content_role.evidence_signal_families",
            ",".join(
                sorted({evidence.signal_family for evidence in annotation.evidence})
            ),
        ),
        (
            "content_role.evidence_reason_codes",
            ",".join(sorted(evidence.reason_code for evidence in annotation.evidence)),
        ),
    )
    for key, value in pairs:
        if not key.startswith("content_role."):
            raise ValueError("content-role metadata key must be namespaced")
        _validate_metadata_scalar(key, value)
    return pairs


def signal_families(signals: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """Return the independent signal-family names present in a fixture row."""

    return frozenset(str(signal.get("signal_family", "")) for signal in signals)


def high_confidence_requirements_met(signals: Sequence[Mapping[str, Any]]) -> bool:
    """Validate the conservative #781 high-confidence evidence floor.

    High confidence requires at least two independent allowed families and at
    least one structural or body-lexical family with strong/medium evidence.
    This is only a fixture contract helper, not a production classifier.
    """

    families = signal_families(signals)
    has_core_strong_or_medium_signal = any(
        signal.get("signal_family") in STRONG_HIGH_CONFIDENCE_FAMILIES
        and signal.get("strength") in {"strong", "medium"}
        for signal in signals
    )
    return (
        len(families) >= 2
        and families <= set(SIGNAL_FAMILIES)
        and has_core_strong_or_medium_signal
    )


def validate_fixture_case(case: Mapping[str, Any]) -> tuple[str, ...]:
    """Return metadata-contract errors for a single content-role fixture case."""

    errors: list[str] = []
    missing = [field for field in REQUIRED_FIXTURE_CASE_FIELDS if field not in case]
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
        return tuple(errors)

    if case["schema_version"] != FIXTURE_SCHEMA_VERSION:
        errors.append("invalid fixture schema_version")
    if case["format_surface"] not in FORMAT_SURFACES:
        errors.append("invalid format_surface")
    if case["expected_role"] not in ALLOWED_ROLES:
        errors.append("invalid expected_role")
    if case["expected_confidence"] not in CONFIDENCE_LEVELS:
        errors.append("invalid expected_confidence")
    for signal_group in ("positive_signals", "negative_signals"):
        for signal in case[signal_group]:
            if signal.get("strength") not in EVIDENCE_CONFIDENCE_LEVELS:
                errors.append(f"invalid {signal_group} strength")
    if case["reporting_bucket"] not in REPORTING_BUCKETS:
        errors.append("invalid reporting_bucket")
    elif (
        case["expected_role"] in ALLOWED_ROLES
        and case["source_structure"].get("granularity") in GRANULARITIES
    ):
        expected_bucket = reporting_bucket_for_annotation(
            role=case["expected_role"],
            granularity=case["source_structure"]["granularity"],
            token_kinds=case["protected_token_expectations"].get("token_kinds", ()),
        )
        if case["reporting_bucket"] != expected_bucket:
            errors.append("reporting_bucket must match deterministic contract")
    if case["allowed_action_envelope"] != SECTION_BLOCK_ACTION_ENVELOPE:
        errors.append("section/block action envelope must remain shadow/report/include")
    if case["behavior_allowed"] is not False:
        errors.append("behavior_allowed must be false")
    if case["raw_publication_allowed"] is not False:
        errors.append("raw_publication_allowed must be false")
    if case["expected_confidence"] == "high" and not high_confidence_requirements_met(
        case["positive_signals"]
    ):
        errors.append(
            "high confidence requires at least two independent allowed signal families"
            " and one strong/medium core signal"
        )

    protected = case["protected_token_expectations"]
    if protected.get("token_action_envelope") != TOKEN_ACTION_ENVELOPE:
        errors.append("protected-token action must be token_preserve_only")
    if protected.get("section_omit_or_preserve_allowed") is not False:
        errors.append(
            "protected-token preservation must not authorize section behavior"
        )

    return tuple(errors)
