from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.book_profile import (
    BOOK_PROFILE_SCHEMA_VERSION,
    PROFILE_GLOSSARY_RULE_SCHEMA_VERSION,
    BookProfileDetection,
)
from translator_service.glossary_contracts import (
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    GlossarySnapshot,
    glossary_snapshot_signature,
)
from translator_service.translation_policy import (
    TranslationPolicy,
    translation_policy_signature,
)

TRANSLATION_CONTRACT_SNAPSHOT_SCHEMA_VERSION = "translation-contract-snapshot-v1"
DEFAULT_DIAGNOSTICS_POLICY_ID = "diagnostics-policy:metadata-only-v1"
TRANSLATION_CONTRACT_SNAPSHOT_RETENTION_POLICY = "TBD"

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}$")


@dataclass(frozen=True)
class TranslationContractSnapshot:
    snapshot_id: str
    snapshot_schema_version: str
    translation_mode: str
    source_language: str
    target_language: str
    glossary_schema_version: str
    glossary_signature: str
    profile_schema_version: str
    profile_signature: str
    selected_rule_ids: tuple[str, ...]
    prompt_policy_version: str
    diagnostics_policy_id: str
    uncertainty_markers: tuple[str, ...]
    translation_policy_signature: str
    protection_policy_version: str
    adapter_policy_version: str
    glossary_snapshot_id: str = "glossary-snapshot:none"
    profile_id: str = "book-profile:none"
    profile_rule_schema_version: str = PROFILE_GLOSSARY_RULE_SCHEMA_VERSION
    profile_detector_version: str = "book-profile-detector:none"
    provider_policy_signature: str | None = None
    pro_role_policy_signature: str | None = None
    selection_policy_version: str | None = None
    quality_route: str | None = None


def build_translation_contract_snapshot(
    policy: TranslationPolicy,
    *,
    glossary_snapshot: GlossarySnapshot | None = None,
    glossary_signature: str | None = None,
    glossary_schema_version: str | None = None,
    profile_detection: BookProfileDetection | None = None,
    profile_signature: str | None = None,
    profile_schema_version: str | None = None,
    selected_rule_ids: Iterable[str] | None = None,
    uncertainty_markers: Iterable[str] | None = None,
    diagnostics_policy_id: str = DEFAULT_DIAGNOSTICS_POLICY_ID,
    translation_mode: str | None = None,
    provider_policy_signature: str | None = None,
    pro_role_policy_signature: str | None = None,
    selection_policy_version: str | None = None,
    quality_route: str | None = None,
) -> TranslationContractSnapshot:
    if glossary_snapshot is not None:
        glossary_signature = glossary_snapshot_signature(glossary_snapshot)
        glossary_schema_version = glossary_snapshot.schema_version
        glossary_snapshot_id = _normalize_identifier(
            glossary_snapshot.snapshot_id,
            field_name="glossary_snapshot_id",
        )
    else:
        glossary_snapshot_id = "glossary-snapshot:none"

    if profile_detection is not None:
        profile = profile_detection.profile
        profile_signature = book_profile_detection_signature(profile_detection)
        profile_schema_version = profile.schema_version
        profile_id = _normalize_identifier(profile.profile_id, field_name="profile_id")
        profile_detector_version = _normalize_identifier(
            profile_detection.detector_version,
            field_name="profile_detector_version",
        )
    else:
        profile_id = "book-profile:none"
        profile_detector_version = "book-profile-detector:none"

    normalized_rule_ids = _normalize_identifier_sequence(
        selected_rule_ids
        if selected_rule_ids is not None
        else (
            rule.rule_id
            for rule in profile_detection.rules
        )
        if profile_detection is not None
        else (),
        field_name="selected_rule_ids",
    )
    normalized_uncertainty_markers = _normalize_identifier_sequence(
        uncertainty_markers
        if uncertainty_markers is not None
        else profile_detection.profile.uncertainty_notes
        if profile_detection is not None
        else (),
        field_name="uncertainty_markers",
    )

    body_payload = _body_payload(
        snapshot_schema_version=TRANSLATION_CONTRACT_SNAPSHOT_SCHEMA_VERSION,
        translation_mode=_normalize_identifier(
            translation_mode or policy.prompt_tier.value,
            field_name="translation_mode",
        ),
        source_language=_normalize_identifier(
            policy.source_language,
            field_name="source_language",
        ),
        target_language=_normalize_identifier(
            policy.target_language,
            field_name="target_language",
        ),
        glossary_schema_version=_normalize_identifier(
            glossary_schema_version or GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
            field_name="glossary_schema_version",
        ),
        glossary_signature=_normalize_identifier(
            glossary_signature or "glossary-snapshot:none",
            field_name="glossary_signature",
        ),
        profile_schema_version=_normalize_identifier(
            profile_schema_version or BOOK_PROFILE_SCHEMA_VERSION,
            field_name="profile_schema_version",
        ),
        profile_signature=_normalize_identifier(
            profile_signature or "book-profile:none",
            field_name="profile_signature",
        ),
        selected_rule_ids=normalized_rule_ids,
        prompt_policy_version=_normalize_identifier(
            policy.prompt_policy_version,
            field_name="prompt_policy_version",
        ),
        diagnostics_policy_id=_normalize_identifier(
            diagnostics_policy_id,
            field_name="diagnostics_policy_id",
        ),
        uncertainty_markers=normalized_uncertainty_markers,
        translation_policy_signature=translation_policy_signature(policy),
        protection_policy_version=_normalize_identifier(
            policy.protection_policy_version,
            field_name="protection_policy_version",
        ),
        adapter_policy_version=_normalize_identifier(
            policy.adapter_policy_version,
            field_name="adapter_policy_version",
        ),
        glossary_snapshot_id=glossary_snapshot_id,
        profile_id=profile_id,
        profile_rule_schema_version=PROFILE_GLOSSARY_RULE_SCHEMA_VERSION,
        profile_detector_version=profile_detector_version,
        provider_policy_signature=_optional_identifier(
            provider_policy_signature,
            field_name="provider_policy_signature",
        ),
        pro_role_policy_signature=_optional_identifier(
            pro_role_policy_signature,
            field_name="pro_role_policy_signature",
        ),
        selection_policy_version=_optional_identifier(
            selection_policy_version,
            field_name="selection_policy_version",
        ),
        quality_route=_optional_identifier(quality_route, field_name="quality_route"),
    )
    snapshot_id = f"translation-snapshot:v1:{_payload_digest(body_payload)}"
    return TranslationContractSnapshot(snapshot_id=snapshot_id, **body_payload)


def translation_contract_snapshot_payload(
    snapshot: TranslationContractSnapshot,
) -> dict[str, Any]:
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        **_body_payload(
            snapshot_schema_version=snapshot.snapshot_schema_version,
            translation_mode=snapshot.translation_mode,
            source_language=snapshot.source_language,
            target_language=snapshot.target_language,
            glossary_schema_version=snapshot.glossary_schema_version,
            glossary_signature=snapshot.glossary_signature,
            profile_schema_version=snapshot.profile_schema_version,
            profile_signature=snapshot.profile_signature,
            selected_rule_ids=snapshot.selected_rule_ids,
            prompt_policy_version=snapshot.prompt_policy_version,
            diagnostics_policy_id=snapshot.diagnostics_policy_id,
            uncertainty_markers=snapshot.uncertainty_markers,
            translation_policy_signature=snapshot.translation_policy_signature,
            protection_policy_version=snapshot.protection_policy_version,
            adapter_policy_version=snapshot.adapter_policy_version,
            glossary_snapshot_id=snapshot.glossary_snapshot_id,
            profile_id=snapshot.profile_id,
            profile_rule_schema_version=snapshot.profile_rule_schema_version,
            profile_detector_version=snapshot.profile_detector_version,
            provider_policy_signature=snapshot.provider_policy_signature,
            pro_role_policy_signature=snapshot.pro_role_policy_signature,
            selection_policy_version=snapshot.selection_policy_version,
            quality_route=snapshot.quality_route,
        ),
    }
    return payload


def serialize_translation_contract_snapshot(
    snapshot: TranslationContractSnapshot,
) -> str:
    return json.dumps(
        translation_contract_snapshot_payload(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def translation_contract_snapshot_signature(
    snapshot: TranslationContractSnapshot,
) -> str:
    digest = _payload_digest(translation_contract_snapshot_payload(snapshot))
    return f"translation-contract-snapshot:v1:{digest}"


def book_profile_detection_signature(detection: BookProfileDetection) -> str:
    profile = detection.profile
    payload = {
        "schema_version": profile.schema_version,
        "detector_version": detection.detector_version,
        "source_language": profile.source_language.strip().lower(),
        "target_language": profile.target_language.strip().lower(),
        "primary_profile": _enum_signature_value(profile.primary_profile),
        "secondary_profiles": sorted(
            _enum_signature_value(item) for item in profile.secondary_profiles
        ),
        "document_type": _enum_signature_value(profile.document_type),
        "fictionality": _enum_signature_value(profile.fictionality),
        "dialogue_density": _enum_signature_value(profile.dialogue_density),
        "register": _enum_signature_value(profile.register),
        "confidence": _confidence_signature_value(profile.confidence),
        "domain_hints": sorted(str(item) for item in profile.domain_hints),
        "terminology_strictness": _enum_signature_value(
            profile.terminology_strictness
        ),
        "paraphrase_allowance": _enum_signature_value(profile.paraphrase_allowance),
        "named_entity_policy": _enum_signature_value(profile.named_entity_policy),
        "source_pair_policy": profile.source_pair_policy,
        "target_language_policy": profile.target_language_policy,
        "evidence_refs": sorted(str(ref) for ref in profile.evidence_refs),
        "uncertainty_notes": sorted(str(note) for note in profile.uncertainty_notes),
        "rule_signatures": sorted(
            _profile_rule_signature(rule) for rule in detection.rules
        ),
        "evidence_signatures": sorted(
            _profile_evidence_signature(evidence) for evidence in detection.evidence
        ),
    }
    return f"book-profile:v1:{_payload_digest(payload)}"


def _body_payload(
    *,
    snapshot_schema_version: str,
    translation_mode: str,
    source_language: str,
    target_language: str,
    glossary_schema_version: str,
    glossary_signature: str,
    profile_schema_version: str,
    profile_signature: str,
    selected_rule_ids: Iterable[str],
    prompt_policy_version: str,
    diagnostics_policy_id: str,
    uncertainty_markers: Iterable[str],
    translation_policy_signature: str,
    protection_policy_version: str,
    adapter_policy_version: str,
    glossary_snapshot_id: str,
    profile_id: str,
    profile_rule_schema_version: str,
    profile_detector_version: str,
    provider_policy_signature: str | None,
    pro_role_policy_signature: str | None,
    selection_policy_version: str | None,
    quality_route: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "snapshot_schema_version": snapshot_schema_version,
        "translation_mode": translation_mode,
        "source_language": source_language,
        "target_language": target_language,
        "glossary_schema_version": glossary_schema_version,
        "glossary_signature": glossary_signature,
        "profile_schema_version": profile_schema_version,
        "profile_signature": profile_signature,
        "selected_rule_ids": list(selected_rule_ids),
        "prompt_policy_version": prompt_policy_version,
        "diagnostics_policy_id": diagnostics_policy_id,
        "uncertainty_markers": list(uncertainty_markers),
        "translation_policy_signature": translation_policy_signature,
        "protection_policy_version": protection_policy_version,
        "adapter_policy_version": adapter_policy_version,
        "glossary_snapshot_id": glossary_snapshot_id,
        "profile_id": profile_id,
        "profile_rule_schema_version": profile_rule_schema_version,
        "profile_detector_version": profile_detector_version,
    }
    optional_fields = {
        "provider_policy_signature": provider_policy_signature,
        "pro_role_policy_signature": pro_role_policy_signature,
        "selection_policy_version": selection_policy_version,
        "quality_route": quality_route,
    }
    payload.update(
        {key: value for key, value in optional_fields.items() if value is not None}
    )
    return payload


def _profile_rule_signature(rule: Any) -> str:
    payload = {
        "schema_version": rule.schema_version,
        "rule_id": rule.rule_id,
        "rule_type": _enum_signature_value(rule.rule_type),
        "applies_to_profiles": sorted(
            _enum_signature_value(item) for item in rule.applies_to_profiles
        ),
        "scope_category": _enum_signature_value(rule.scope_category),
        "target_languages": sorted(
            str(item).strip().lower() for item in rule.target_languages
        ),
        "glossary_strategy": _enum_signature_value(rule.glossary_strategy),
        "terminology_strictness": _enum_signature_value(rule.terminology_strictness),
        "paraphrase_allowance": _enum_signature_value(rule.paraphrase_allowance),
        "named_entity_policy": _enum_signature_value(rule.named_entity_policy),
        "fallback_strategy": _enum_signature_value(rule.fallback_strategy),
        "evidence_refs": sorted(str(ref) for ref in rule.evidence_refs),
        "requires_review": bool(rule.requires_review),
    }
    return f"profile-glossary-rule:v1:{_payload_digest(payload)}"


def _profile_evidence_signature(evidence: Any) -> str:
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
    return f"book-profile-evidence:v1:{_payload_digest(payload)}"


def _normalize_identifier_sequence(
    values: Iterable[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _normalize_identifier(value, field_name=f"{field_name}[]")
                for value in values
            }
        )
    )


def _optional_identifier(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _normalize_identifier(value, field_name=field_name)


def _normalize_identifier(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    normalized = value.strip()
    if not _SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a compact identifier.")
    return normalized


def _enum_signature_value(value: Any) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)


def _confidence_signature_value(value: Any) -> str:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return f"{float(value):.6f}"
    return str(value)


def _payload_digest(payload: Mapping[str, Any] | Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
