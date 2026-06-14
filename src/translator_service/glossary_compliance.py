from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from translator_service.glossary_contracts import GlossaryEntry
from translator_service.glossary_terminology_policy import (
    DEFAULT_TERMINOLOGY_POLICY_REASON_CODES,
    TERMINOLOGY_POLICY_MATCH_SCHEMA_VERSION,
    AllowedVariantStrategy,
    ForbiddenVariantStrategy,
    TerminologyMatchMode,
    TerminologyMatchStatus,
    TerminologyNormalizationMode,
    TerminologyPolicy,
    TerminologyPolicyReasonCode,
    TerminologyPolicyRegistry,
    UnsupportedTerminologyFallback,
    match_terminology_target,
    terminology_match_payload,
    terminology_policy_resolution_payload,
)

GLOSSARY_COMPLIANCE_SCHEMA_VERSION = "glossary-compliance-v2"
GLOSSARY_COMPLIANCE_POLICY = "exact_configured_target_forms_only_v1"
GLOSSARY_COMPLIANCE_TERMINOLOGY_POLICY = "terminology_policy_registry_adapter_v1"

_DEFAULT_EXACT_TERMINOLOGY_POLICY = TerminologyPolicy(
    policy_id="terminology_policy.glossary_compliance.exact_configured_target_forms",
    policy_version="v1",
    target_language=None,
    language_family="generic",
    match_mode=TerminologyMatchMode.EXACT,
    normalization_mode=TerminologyNormalizationMode.NFC,
    allowed_variant_strategy=AllowedVariantStrategy.CANONICAL_AND_VARIANTS,
    forbidden_variant_strategy=ForbiddenVariantStrategy.IGNORE,
    unsupported_fallback=UnsupportedTerminologyFallback.MANUAL_REVIEW_REQUIRED,
    reason_codes=DEFAULT_TERMINOLOGY_POLICY_REASON_CODES,
)


class GlossaryComplianceStatus(StrEnum):
    PASS = "pass"
    FINDINGS = "findings"
    SKIPPED = "skipped"


class GlossaryComplianceReason(StrEnum):
    TARGET_FORM_PRESENT = "target_form_present"
    TARGET_FORM_MISSING = "target_form_missing"
    TARGET_METADATA_MISSING = "target_metadata_missing"
    SOURCE_TERM_ABSENT = "source_term_absent"
    GLOSSARY_CONTEXT_OMITTED = "glossary_context_omitted"
    MISSING_SELECTED_ENTRY = "missing_selected_entry"
    NO_SELECTED_ENTRIES = "no_selected_entries"
    STRUCTURAL_VALIDATION_FAILED = "structural_validation_failed"
    MORPHOLOGY_POLICY_TBD = "morphology_policy_tbd"


def validate_glossary_compliance(
    entries: Iterable[GlossaryEntry | Mapping[str, Any]],
    *,
    selected_entry_ids: Iterable[str],
    source_text: str,
    translated_text: str | None,
    included_entry_ids: Iterable[str] | None = None,
    structural_validation_passed: bool = True,
    target_language: str | None = None,
    language_family: str | None = None,
    terminology_policy_registry: TerminologyPolicyRegistry | None = None,
) -> dict[str, Any]:
    """Return metadata-only glossary target-form compliance for a smoke output."""

    policy_resolution = _resolve_terminology_policy(
        target_language=target_language,
        language_family=language_family,
        registry=terminology_policy_registry,
    )
    terminology_policy = _active_terminology_policy(policy_resolution)
    selected_ids = _unique_ids(selected_entry_ids)
    included_ids = (
        set(_unique_ids(included_entry_ids))
        if included_entry_ids is not None
        else set(selected_ids)
    )
    entries_by_id = {
        entry_id: entry
        for entry in entries
        if (entry_id := _text_value(entry, "entry_id")) is not None
    }

    entry_results: list[dict[str, Any]] = []
    checked_entry_ids: list[str] = []
    target_form_present_entry_ids: list[str] = []
    target_form_missing_entry_ids: list[str] = []
    forbidden_variant_entry_ids: list[str] = []
    needs_review_entry_ids: list[str] = []
    skipped_entry_ids: list[str] = []

    if not structural_validation_passed:
        return _payload(
            status=GlossaryComplianceStatus.SKIPPED,
            selected_entry_ids=selected_ids,
            checked_entry_ids=(),
            target_form_present_entry_ids=(),
            target_form_missing_entry_ids=(),
            forbidden_variant_entry_ids=(),
            needs_review_entry_ids=(),
            skipped_entry_ids=selected_ids,
            entry_results=[
                _entry_result(
                    entry_id,
                    checked=False,
                    target_form_present=False,
                    reason_codes=(
                        GlossaryComplianceReason.STRUCTURAL_VALIDATION_FAILED,
                    ),
                )
                for entry_id in selected_ids
            ],
            reason_codes=(GlossaryComplianceReason.STRUCTURAL_VALIDATION_FAILED,),
            terminology_policy=_terminology_policy_payload(policy_resolution),
        )

    if not selected_ids:
        return _payload(
            status=GlossaryComplianceStatus.SKIPPED,
            selected_entry_ids=(),
            checked_entry_ids=(),
            target_form_present_entry_ids=(),
            target_form_missing_entry_ids=(),
            forbidden_variant_entry_ids=(),
            needs_review_entry_ids=(),
            skipped_entry_ids=(),
            entry_results=(),
            reason_codes=(GlossaryComplianceReason.NO_SELECTED_ENTRIES,),
            terminology_policy=_terminology_policy_payload(policy_resolution),
        )

    for entry_id in selected_ids:
        entry = entries_by_id.get(entry_id)
        if entry is None:
            skipped_entry_ids.append(entry_id)
            entry_results.append(
                _entry_result(
                    entry_id,
                    checked=False,
                    target_form_present=False,
                    reason_codes=(GlossaryComplianceReason.MISSING_SELECTED_ENTRY,),
                )
            )
            continue

        if entry_id not in included_ids:
            skipped_entry_ids.append(entry_id)
            entry_results.append(
                _entry_result(
                    entry_id,
                    checked=False,
                    target_form_present=False,
                    reason_codes=(GlossaryComplianceReason.GLOSSARY_CONTEXT_OMITTED,),
                )
            )
            continue

        if not _entry_source_matches(entry, source_text):
            skipped_entry_ids.append(entry_id)
            entry_results.append(
                _entry_result(
                    entry_id,
                    checked=False,
                    target_form_present=False,
                    reason_codes=(GlossaryComplianceReason.SOURCE_TERM_ABSENT,),
                )
            )
            continue

        target_forms = _entry_target_forms(entry)
        if not target_forms:
            skipped_entry_ids.append(entry_id)
            entry_results.append(
                _entry_result(
                    entry_id,
                    checked=False,
                    target_form_present=False,
                    reason_codes=(GlossaryComplianceReason.TARGET_METADATA_MISSING,),
                )
            )
            continue

        if terminology_policy is None:
            needs_review_entry_ids.append(entry_id)
            entry_results.append(
                _entry_result(
                    entry_id,
                    checked=False,
                    target_form_present=False,
                    reason_codes=_policy_resolution_reason_codes(policy_resolution),
                    terminology_match=_unsupported_terminology_match_payload(
                        policy_resolution
                    ),
                )
            )
            continue

        match_result = match_terminology_target(
            terminology_policy,
            translated_text=translated_text,
            target_canonical=_text_value(entry, "target_canonical"),
            target_variants=_sequence_value(entry, "target_variants"),
            forbidden_variants=_sequence_value(entry, "forbidden_variants"),
        )
        if match_result.checked:
            checked_entry_ids.append(entry_id)
        target_form_present = match_result.status is TerminologyMatchStatus.MATCH
        if match_result.status is TerminologyMatchStatus.MATCH:
            target_form_present_entry_ids.append(entry_id)
        elif match_result.status is TerminologyMatchStatus.NO_MATCH:
            target_form_missing_entry_ids.append(entry_id)
        elif match_result.status is TerminologyMatchStatus.FORBIDDEN_VARIANT:
            forbidden_variant_entry_ids.append(entry_id)
        else:
            needs_review_entry_ids.append(entry_id)
        reason_codes = _entry_reason_codes_for_match(match_result)
        entry_results.append(
            _entry_result(
                entry_id,
                checked=match_result.checked,
                target_form_present=target_form_present,
                reason_codes=reason_codes,
                terminology_match=terminology_match_payload(match_result),
            )
        )

    if not checked_entry_ids and not needs_review_entry_ids:
        status = GlossaryComplianceStatus.SKIPPED
    elif (
        target_form_missing_entry_ids
        or forbidden_variant_entry_ids
        or needs_review_entry_ids
    ):
        status = GlossaryComplianceStatus.FINDINGS
    else:
        status = GlossaryComplianceStatus.PASS

    reason_codes = _reason_codes_from_entries(entry_results)
    return _payload(
        status=status,
        selected_entry_ids=selected_ids,
        checked_entry_ids=checked_entry_ids,
        target_form_present_entry_ids=target_form_present_entry_ids,
        target_form_missing_entry_ids=target_form_missing_entry_ids,
        forbidden_variant_entry_ids=forbidden_variant_entry_ids,
        needs_review_entry_ids=needs_review_entry_ids,
        skipped_entry_ids=skipped_entry_ids,
        entry_results=entry_results,
        reason_codes=reason_codes,
        include_morphology_caveat=bool(
            checked_entry_ids or needs_review_entry_ids
        ),
        terminology_policy=_terminology_policy_payload(policy_resolution),
    )


def _resolve_terminology_policy(
    *,
    target_language: str | None,
    language_family: str | None,
    registry: TerminologyPolicyRegistry | None,
):
    if registry is None:
        return None
    return registry.resolve(target_language, language_family=language_family)


def _active_terminology_policy(policy_resolution) -> TerminologyPolicy | None:
    if policy_resolution is None:
        return _DEFAULT_EXACT_TERMINOLOGY_POLICY
    if policy_resolution.supported and policy_resolution.policy is not None:
        return policy_resolution.policy
    return None


def _terminology_policy_payload(policy_resolution) -> dict[str, Any]:
    if policy_resolution is None:
        return {
            "enabled": False,
            "compliance_policy": GLOSSARY_COMPLIANCE_POLICY,
            "policy_id": _DEFAULT_EXACT_TERMINOLOGY_POLICY.policy_id,
            "policy_version": _DEFAULT_EXACT_TERMINOLOGY_POLICY.policy_version,
            "match_mode": TerminologyMatchMode.EXACT.value,
            "supported": True,
            "fallback": UnsupportedTerminologyFallback.MANUAL_REVIEW_REQUIRED.value,
            "reason_codes": [],
            "metadata_only": True,
            "raw_payload_included": False,
            "semantic_quality_claim_made": False,
            "full_morphology_claim_made": False,
        }
    payload = terminology_policy_resolution_payload(policy_resolution)
    policy = policy_resolution.policy
    payload.update(
        {
            "enabled": True,
            "compliance_policy": GLOSSARY_COMPLIANCE_TERMINOLOGY_POLICY,
            "match_mode": (
                TerminologyMatchMode(policy.match_mode).value
                if policy is not None
                else None
            ),
        }
    )
    return payload


def _policy_resolution_reason_codes(policy_resolution) -> tuple[str, ...]:
    if policy_resolution is None:
        return ()
    return tuple(
        reason.value
        if isinstance(reason, TerminologyPolicyReasonCode)
        else str(reason)
        for reason in policy_resolution.reason_codes
    )


def _unsupported_terminology_match_payload(policy_resolution) -> dict[str, Any]:
    return {
        "schema_version": TERMINOLOGY_POLICY_MATCH_SCHEMA_VERSION,
        "policy_id": None,
        "policy_version": None,
        "match_mode": None,
        "status": TerminologyMatchStatus.NEEDS_REVIEW.value,
        "checked": False,
        "local_form_match": False,
        "forbidden_form_match": False,
        "matched_form_kind": None,
        "reason_codes": sorted(set(_policy_resolution_reason_codes(policy_resolution))),
        "metadata_only": True,
        "raw_payload_included": False,
        "semantic_quality_claim_made": False,
        "full_morphology_claim_made": False,
    }


def _entry_reason_codes_for_match(match_result) -> tuple[str, ...]:
    reason_codes = [
        reason.value
        if isinstance(reason, TerminologyPolicyReasonCode)
        else str(reason)
        for reason in match_result.reason_codes
    ]
    if match_result.status is TerminologyMatchStatus.MATCH:
        reason_codes.append(GlossaryComplianceReason.TARGET_FORM_PRESENT.value)
    elif match_result.status is TerminologyMatchStatus.NO_MATCH:
        reason_codes.append(GlossaryComplianceReason.TARGET_FORM_MISSING.value)
    return tuple(dict.fromkeys(reason_codes))


def _payload(
    *,
    status: GlossaryComplianceStatus,
    selected_entry_ids: Sequence[str],
    checked_entry_ids: Sequence[str],
    target_form_present_entry_ids: Sequence[str],
    target_form_missing_entry_ids: Sequence[str],
    forbidden_variant_entry_ids: Sequence[str],
    needs_review_entry_ids: Sequence[str],
    skipped_entry_ids: Sequence[str],
    entry_results: Sequence[Mapping[str, Any]],
    reason_codes: Sequence[GlossaryComplianceReason | str],
    include_morphology_caveat: bool = False,
    terminology_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    uncertainty_reason_codes = (
        [GlossaryComplianceReason.MORPHOLOGY_POLICY_TBD.value]
        if include_morphology_caveat
        else []
    )
    terminology_policy_payload = dict(terminology_policy or {})
    return {
        "schema_version": GLOSSARY_COMPLIANCE_SCHEMA_VERSION,
        "policy": terminology_policy_payload.get(
            "compliance_policy",
            GLOSSARY_COMPLIANCE_POLICY,
        ),
        "terminology_policy": terminology_policy_payload,
        "status": status.value,
        "reason_codes": _sorted_reason_values(reason_codes),
        "uncertainty_reason_codes": uncertainty_reason_codes,
        "selected_entry_count": len(selected_entry_ids),
        "checked_entry_count": len(checked_entry_ids),
        "target_form_present_count": len(target_form_present_entry_ids),
        "target_form_missing_count": len(target_form_missing_entry_ids),
        "forbidden_variant_count": len(forbidden_variant_entry_ids),
        "needs_review_entry_count": len(needs_review_entry_ids),
        "skipped_entry_count": len(skipped_entry_ids),
        "selected_entry_ids": list(selected_entry_ids),
        "checked_entry_ids": list(checked_entry_ids),
        "target_form_present_entry_ids": list(target_form_present_entry_ids),
        "target_form_missing_entry_ids": list(target_form_missing_entry_ids),
        "forbidden_variant_entry_ids": list(forbidden_variant_entry_ids),
        "needs_review_entry_ids": list(needs_review_entry_ids),
        "skipped_entry_ids": list(skipped_entry_ids),
        "entries": [dict(item) for item in entry_results],
        "metadata_only": True,
        "raw_payload_included": False,
        "semantic_quality_claim_made": False,
    }


def _entry_result(
    entry_id: str,
    *,
    checked: bool,
    target_form_present: bool,
    reason_codes: Sequence[GlossaryComplianceReason | str],
    terminology_match: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "entry_id": entry_id,
        "checked": checked,
        "target_form_present": target_form_present,
        "reason_codes": _sorted_reason_values(reason_codes),
    }
    if terminology_match is not None:
        payload["terminology_match"] = dict(terminology_match)
    return payload


def _unique_ids(values: Iterable[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = str(value).strip()
        if not candidate or candidate in seen:
            continue
        ids.append(candidate)
        seen.add(candidate)
    return tuple(ids)


def _reason_codes_from_entries(
    entry_results: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    non_finding_codes = {
        GlossaryComplianceReason.TARGET_FORM_PRESENT.value,
        TerminologyPolicyReasonCode.POLICY_EXACT_MATCH.value,
        TerminologyPolicyReasonCode.POLICY_CASEFOLD_MATCH.value,
        TerminologyPolicyReasonCode.POLICY_VARIANT_MATCH.value,
        TerminologyPolicyReasonCode.SEMANTIC_TRUTH_NOT_PROVEN.value,
    }
    codes: list[str] = []
    for entry in entry_results:
        for reason in entry.get("reason_codes", ()):
            if reason in non_finding_codes:
                continue
            codes.append(str(reason))
    return tuple(sorted(set(codes)))


def _sorted_reason_values(
    reason_codes: Sequence[GlossaryComplianceReason | str],
) -> list[str]:
    return sorted(
        {
            (
                reason.value
                if isinstance(reason, GlossaryComplianceReason)
                else str(reason)
            )
            for reason in reason_codes
        }
    )


def _entry_source_matches(
    entry: GlossaryEntry | Mapping[str, Any],
    source_text: str,
) -> bool:
    if not source_text:
        return False
    return any(
        _source_term_present(term, source_text) for term in _entry_source_terms(entry)
    )


def _entry_source_terms(
    entry: GlossaryEntry | Mapping[str, Any],
) -> tuple[str, ...]:
    terms: list[str] = []
    source_canonical = _text_value(entry, "source_canonical")
    if source_canonical is not None:
        terms.append(source_canonical)
    aliases = _sequence_value(entry, "aliases")
    terms.extend(aliases)
    return tuple(dict.fromkeys(terms))


def _entry_target_forms(
    entry: GlossaryEntry | Mapping[str, Any],
) -> tuple[str, ...]:
    forms: list[str] = []
    target_canonical = _text_value(entry, "target_canonical")
    if target_canonical is not None:
        forms.append(target_canonical)
    target_variants = _sequence_value(entry, "target_variants")
    forms.extend(target_variants)
    return tuple(dict.fromkeys(forms))


def _text_value(
    entry: GlossaryEntry | Mapping[str, Any],
    field_name: str,
) -> str | None:
    value = (
        entry.get(field_name)
        if isinstance(entry, Mapping)
        else getattr(entry, field_name, None)
    )
    if not isinstance(value, str):
        return None
    value = _normalize_text(value)
    return value or None


def _sequence_value(
    entry: GlossaryEntry | Mapping[str, Any],
    field_name: str,
) -> tuple[str, ...]:
    value = (
        entry.get(field_name)
        if isinstance(entry, Mapping)
        else getattr(entry, field_name, ())
    )
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    return tuple(
        normalized
        for item in value
        if isinstance(item, str) and (normalized := _normalize_text(item))
    )


def _source_term_present(term: str, source_text: str) -> bool:
    return _bounded_literal_present(term, source_text, flags=re.IGNORECASE)


def _target_form_present(form: str, translated_text: str) -> bool:
    return _bounded_literal_present(form, translated_text, flags=0)


def _bounded_literal_present(term: str, text: str, *, flags: int) -> bool:
    normalized_term = _normalize_text(term)
    normalized_text = _normalize_text(text)
    if not normalized_term or not normalized_text:
        return False
    pattern = re.escape(normalized_term)
    if normalized_term[0].isalnum():
        pattern = rf"(?<!\w){pattern}"
    if normalized_term[-1].isalnum():
        pattern = rf"{pattern}(?!\w)"
    return re.search(pattern, normalized_text, flags=flags) is not None


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()
