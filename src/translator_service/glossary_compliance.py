from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from translator_service.glossary_contracts import GlossaryEntry

GLOSSARY_COMPLIANCE_SCHEMA_VERSION = "glossary-compliance-v1"
GLOSSARY_COMPLIANCE_POLICY = "exact_configured_target_forms_only_v1"


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
) -> dict[str, Any]:
    """Return metadata-only glossary target-form compliance for a smoke output."""

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
    skipped_entry_ids: list[str] = []

    if not structural_validation_passed:
        return _payload(
            status=GlossaryComplianceStatus.SKIPPED,
            selected_entry_ids=selected_ids,
            checked_entry_ids=(),
            target_form_present_entry_ids=(),
            target_form_missing_entry_ids=(),
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
        )

    if not selected_ids:
        return _payload(
            status=GlossaryComplianceStatus.SKIPPED,
            selected_entry_ids=(),
            checked_entry_ids=(),
            target_form_present_entry_ids=(),
            target_form_missing_entry_ids=(),
            skipped_entry_ids=(),
            entry_results=(),
            reason_codes=(GlossaryComplianceReason.NO_SELECTED_ENTRIES,),
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

        checked_entry_ids.append(entry_id)
        target_form_present = (
            translated_text is not None
            and any(
                _target_form_present(form, translated_text) for form in target_forms
            )
        )
        if target_form_present:
            target_form_present_entry_ids.append(entry_id)
            reason_codes = (GlossaryComplianceReason.TARGET_FORM_PRESENT,)
        else:
            target_form_missing_entry_ids.append(entry_id)
            reason_codes = (GlossaryComplianceReason.TARGET_FORM_MISSING,)
        entry_results.append(
            _entry_result(
                entry_id,
                checked=True,
                target_form_present=target_form_present,
                reason_codes=reason_codes,
            )
        )

    if not checked_entry_ids:
        status = GlossaryComplianceStatus.SKIPPED
    elif target_form_missing_entry_ids:
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
        skipped_entry_ids=skipped_entry_ids,
        entry_results=entry_results,
        reason_codes=reason_codes,
        include_morphology_caveat=bool(checked_entry_ids),
    )


def _payload(
    *,
    status: GlossaryComplianceStatus,
    selected_entry_ids: Sequence[str],
    checked_entry_ids: Sequence[str],
    target_form_present_entry_ids: Sequence[str],
    target_form_missing_entry_ids: Sequence[str],
    skipped_entry_ids: Sequence[str],
    entry_results: Sequence[Mapping[str, Any]],
    reason_codes: Sequence[GlossaryComplianceReason | str],
    include_morphology_caveat: bool = False,
) -> dict[str, Any]:
    uncertainty_reason_codes = (
        [GlossaryComplianceReason.MORPHOLOGY_POLICY_TBD.value]
        if include_morphology_caveat
        else []
    )
    return {
        "schema_version": GLOSSARY_COMPLIANCE_SCHEMA_VERSION,
        "policy": GLOSSARY_COMPLIANCE_POLICY,
        "status": status.value,
        "reason_codes": _sorted_reason_values(reason_codes),
        "uncertainty_reason_codes": uncertainty_reason_codes,
        "selected_entry_count": len(selected_entry_ids),
        "checked_entry_count": len(checked_entry_ids),
        "target_form_present_count": len(target_form_present_entry_ids),
        "target_form_missing_count": len(target_form_missing_entry_ids),
        "skipped_entry_count": len(skipped_entry_ids),
        "selected_entry_ids": list(selected_entry_ids),
        "checked_entry_ids": list(checked_entry_ids),
        "target_form_present_entry_ids": list(target_form_present_entry_ids),
        "target_form_missing_entry_ids": list(target_form_missing_entry_ids),
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
) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "checked": checked,
        "target_form_present": target_form_present,
        "reason_codes": _sorted_reason_values(reason_codes),
    }


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
    codes: list[str] = []
    for entry in entry_results:
        for reason in entry.get("reason_codes", ()):
            if reason == GlossaryComplianceReason.TARGET_FORM_PRESENT.value:
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
