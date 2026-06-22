"""Metadata-only content-role vocabulary for #781 fixture contracts.

This module intentionally defines constants and validation helpers only. It does
not annotate adapters, alter translation output, change provider/profile/cache
behavior, or approve any gate/report persistence change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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


def signal_families(signals: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """Return the independent signal-family names present in a fixture row."""

    return frozenset(str(signal.get("signal_family", "")) for signal in signals)


def high_confidence_requirements_met(signals: Sequence[Mapping[str, Any]]) -> bool:
    """Validate the conservative #781 high-confidence evidence floor.

    High confidence requires at least two independent allowed families and at
    least one strong structural or body-lexical family. This is only a fixture
    contract helper, not a production classifier.
    """

    families = signal_families(signals)
    return (
        len(families) >= 2
        and families <= set(SIGNAL_FAMILIES)
        and bool(families & STRONG_HIGH_CONFIDENCE_FAMILIES)
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
            "high confidence requires at least two independent strong signals"
        )

    protected = case["protected_token_expectations"]
    if protected.get("token_action_envelope") != TOKEN_ACTION_ENVELOPE:
        errors.append("protected-token action must be token_preserve_only")
    if protected.get("section_omit_or_preserve_allowed") is not False:
        errors.append(
            "protected-token preservation must not authorize section behavior"
        )

    return tuple(errors)
