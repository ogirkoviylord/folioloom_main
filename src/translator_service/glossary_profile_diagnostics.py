from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from translator_service.json_utils import read_json_file

GLOSSARY_PROFILE_DIAGNOSTIC_SIDECAR_SCHEMA_VERSION = (
    "glossary-profile-diagnostics-sidecar-v1"
)
GLOSSARY_PROFILE_DIAGNOSTIC_SCOPE = "owner_only_glossary_profile_diagnostics"
GLOSSARY_PROFILE_DIAGNOSTIC_FILENAME = "glossary_profile_diagnostics.json"

_TBD_POLICY = "TBD"
_UNKNOWN = "Unknown"
_OWNER_ONLY = "owner_only"
_FORBIDDEN = "forbidden"


class RawFieldClassification(StrEnum):
    RAW_SOURCE_TEXT = "raw_source_text"
    RAW_TRANSLATED_TEXT = "raw_translated_text"
    NEAR_RAW_CANDIDATE_TEXT = "near_raw_candidate_text"
    PROMPT_BODY = "prompt_body"
    PROVIDER_REQUEST_BODY = "provider_request_body"
    PROVIDER_RESPONSE_BODY = "provider_response_body"
    MODEL_OUTPUT_BODY = "model_output_body"
    OWNER_NOTE = "owner_note"
    DIAGNOSTIC_ERROR_DETAIL = "diagnostic_error_detail"


class GlossaryProfileDiagnosticValidationCode(StrEnum):
    MISSING_FIELD = "missing_field"
    INVALID_SCHEMA_VERSION = "invalid_schema_version"
    INVALID_SCOPE = "invalid_scope"
    INVALID_ACCESS_BOUNDARY = "invalid_access_boundary"
    INVALID_POLICY = "invalid_policy"
    INVALID_MANIFEST_ENTRY = "invalid_manifest_entry"
    MISSING_RAW_FIELD_MANIFEST_ENTRY = "missing_raw_field_manifest_entry"
    SECRET_MATERIAL = "secret_material"
    INVALID_FILENAME = "invalid_filename"


@dataclass(frozen=True)
class RawFieldManifestEntry:
    path: str
    classification: RawFieldClassification | str
    source: str
    allowed_in_archive: str = _TBD_POLICY
    redaction: str = "none_inside_owner_only_sidecar"

    def to_payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "classification": str(self.classification),
            "required_boundary": _OWNER_ONLY,
            "source": self.source,
            "allowed_in_archive": self.allowed_in_archive,
            "redaction": self.redaction,
            "ordinary_surface_policy": _FORBIDDEN,
        }


@dataclass(frozen=True)
class GlossaryProfileDiagnosticValidationIssue:
    code: GlossaryProfileDiagnosticValidationCode
    path: str
    message: str


@dataclass(frozen=True)
class GlossaryProfileDiagnosticValidationResult:
    issues: tuple[GlossaryProfileDiagnosticValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


_REQUIRED_ACCESS_BOUNDARY: dict[str, Any] = {
    "visibility": _OWNER_ONLY,
    "admin_boundary": "ssh_tunneled_admin_session_required",
    "ordinary_logs_allowed": False,
    "telemetry_allowed": False,
    "json_api_allowed": False,
    "support_artifact_allowed": False,
    "release_artifact_allowed": False,
    "github_issue_or_pr_allowed": False,
    "cache_control": "no-store",
}

_RAW_CAPABLE_FIELD_NAMES = frozenset(
    {
        "raw_candidate_text",
        "raw_alias_texts",
        "raw_rejected_candidate_text",
        "raw_source_excerpt",
        "raw_translated_excerpt",
        "near_raw_context_window",
        "raw_profile_evidence_excerpt",
        "raw_mixed_section_note",
        "raw_prompt_body",
        "raw_provider_request_body",
        "raw_provider_response_body",
        "raw_model_output_body",
        "raw_repair_prompt_body",
        "raw_invalid_value",
        "raw_invalid_payload_excerpt",
        "raw_conflicting_claim",
        "raw_conflicting_output_excerpt",
        "raw_observed_variant",
        "raw_owner_note",
    }
)

_SECRET_KEY_FRAGMENTS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "password",
        "token",
        "dsn",
        "secret",
    }
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def default_glossary_profile_access_boundary() -> dict[str, Any]:
    return dict(_REQUIRED_ACCESS_BOUNDARY)


def build_glossary_profile_diagnostic_sidecar(
    *,
    run_or_fixture_ref: str,
    source_language: str = _UNKNOWN,
    target_language: str = _UNKNOWN,
    translation_mode: str = _UNKNOWN,
    translation_snapshot_ref: str = _UNKNOWN,
    glossary_signature: str = _UNKNOWN,
    profile_signature: str = _UNKNOWN,
    raw_text_field_manifest: Sequence[RawFieldManifestEntry | Mapping[str, Any]] = (),
    sections: Mapping[str, Any] | None = None,
    created_at: str | None = None,
    related_diagnostic_files: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "sidecar_schema_version": (
            GLOSSARY_PROFILE_DIAGNOSTIC_SIDECAR_SCHEMA_VERSION
        ),
        "diagnostic_scope": GLOSSARY_PROFILE_DIAGNOSTIC_SCOPE,
        "access_boundary": default_glossary_profile_access_boundary(),
        "run_or_fixture_ref": run_or_fixture_ref,
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "source_language": source_language or _UNKNOWN,
        "target_language": target_language or _UNKNOWN,
        "translation_mode": translation_mode or _UNKNOWN,
        "translation_snapshot_ref": translation_snapshot_ref or _UNKNOWN,
        "glossary_signature": glossary_signature or _UNKNOWN,
        "profile_signature": profile_signature or _UNKNOWN,
        "raw_text_field_manifest": [
            _manifest_entry_payload(entry) for entry in raw_text_field_manifest
        ],
        "secret_exclusion_policy": (
            "Provider Authorization headers, API keys, plaintext provider keys, "
            "passwords, tokens, DSNs and real .env* values are forbidden."
        ),
        "retention_policy": _TBD_POLICY,
        "export_policy": _TBD_POLICY,
        "deletion_policy": _TBD_POLICY,
        "related_diagnostic_files": list(related_diagnostic_files),
        "sections": dict(sections or {}),
    }


def validate_glossary_profile_diagnostic_sidecar(
    sidecar: Mapping[str, Any],
) -> GlossaryProfileDiagnosticValidationResult:
    issues: list[GlossaryProfileDiagnosticValidationIssue] = []
    _validate_required_fields(sidecar, issues)
    if (
        sidecar.get("sidecar_schema_version")
        != GLOSSARY_PROFILE_DIAGNOSTIC_SIDECAR_SCHEMA_VERSION
    ):
        _add_issue(
            issues,
            GlossaryProfileDiagnosticValidationCode.INVALID_SCHEMA_VERSION,
            "sidecar_schema_version",
            "sidecar_schema_version must match the approved glossary/profile "
            "diagnostic sidecar schema.",
        )
    if sidecar.get("diagnostic_scope") != GLOSSARY_PROFILE_DIAGNOSTIC_SCOPE:
        _add_issue(
            issues,
            GlossaryProfileDiagnosticValidationCode.INVALID_SCOPE,
            "diagnostic_scope",
            "diagnostic_scope must be owner_only_glossary_profile_diagnostics.",
        )
    _validate_access_boundary(sidecar.get("access_boundary"), issues)
    _validate_tbd_policy(sidecar, "retention_policy", issues)
    _validate_tbd_policy(sidecar, "export_policy", issues)
    _validate_tbd_policy(sidecar, "deletion_policy", issues)
    manifest_paths = _validate_manifest(
        sidecar.get("raw_text_field_manifest"),
        issues,
    )
    raw_paths = {
        path
        for path, value in _iter_raw_capable_values(
            sidecar.get("sections"),
            "sections",
        )
        if _has_content(value)
    }
    for raw_path in sorted(raw_paths):
        if raw_path not in manifest_paths:
            _add_issue(
                issues,
                GlossaryProfileDiagnosticValidationCode.MISSING_RAW_FIELD_MANIFEST_ENTRY,
                raw_path,
                "raw-capable sidecar fields require a raw_text_field_manifest entry.",
            )
    for secret_path in _iter_secret_material_paths(sidecar):
        _add_issue(
            issues,
            GlossaryProfileDiagnosticValidationCode.SECRET_MATERIAL,
            secret_path,
            "sidecar payload must not contain provider auth material or secrets.",
        )
    return GlossaryProfileDiagnosticValidationResult(issues=tuple(issues))


def glossary_profile_diagnostic_metadata_summary(
    sidecar: Mapping[str, Any],
) -> dict[str, Any]:
    sections = sidecar.get("sections")
    manifest = sidecar.get("raw_text_field_manifest")
    return {
        "sidecar_schema_version": sidecar.get("sidecar_schema_version", _UNKNOWN),
        "diagnostic_scope": sidecar.get("diagnostic_scope", _UNKNOWN),
        "run_or_fixture_ref": sidecar.get("run_or_fixture_ref", _UNKNOWN),
        "source_language": sidecar.get("source_language", _UNKNOWN),
        "target_language": sidecar.get("target_language", _UNKNOWN),
        "translation_mode": sidecar.get("translation_mode", _UNKNOWN),
        "translation_snapshot_ref": sidecar.get(
            "translation_snapshot_ref",
            _UNKNOWN,
        ),
        "glossary_signature": sidecar.get("glossary_signature", _UNKNOWN),
        "profile_signature": sidecar.get("profile_signature", _UNKNOWN),
        "retention_policy": sidecar.get("retention_policy", _TBD_POLICY),
        "export_policy": sidecar.get("export_policy", _TBD_POLICY),
        "deletion_policy": sidecar.get("deletion_policy", _TBD_POLICY),
        "access_boundary": dict(sidecar.get("access_boundary") or {}),
        "raw_field_manifest_count": len(manifest) if isinstance(manifest, list) else 0,
        "raw_field_classifications": sorted(
            {
                str(entry.get("classification"))
                for entry in manifest or []
                if isinstance(entry, Mapping) and entry.get("classification")
            }
        ),
        "section_counts": _section_counts(sections),
        "related_diagnostic_files": list(sidecar.get("related_diagnostic_files") or ()),
    }


def write_glossary_profile_diagnostic_sidecar(
    path: Path,
    sidecar: Mapping[str, Any],
) -> None:
    if path.name != GLOSSARY_PROFILE_DIAGNOSTIC_FILENAME:
        raise ValueError(
            f"glossary/profile diagnostics must be written to "
            f"{GLOSSARY_PROFILE_DIAGNOSTIC_FILENAME}"
        )
    result = validate_glossary_profile_diagnostic_sidecar(sidecar)
    if not result.valid:
        messages = "; ".join(f"{issue.path}: {issue.code}" for issue in result.issues)
        raise ValueError(f"invalid glossary/profile diagnostic sidecar: {messages}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_glossary_profile_diagnostic_sidecar(path: Path) -> dict[str, Any]:
    if path.name != GLOSSARY_PROFILE_DIAGNOSTIC_FILENAME:
        raise ValueError(
            f"glossary/profile diagnostics must be read from "
            f"{GLOSSARY_PROFILE_DIAGNOSTIC_FILENAME}"
        )
    payload = read_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("glossary/profile diagnostic sidecar root must be an object")
    result = validate_glossary_profile_diagnostic_sidecar(payload)
    if not result.valid:
        messages = "; ".join(f"{issue.path}: {issue.code}" for issue in result.issues)
        raise ValueError(f"invalid glossary/profile diagnostic sidecar: {messages}")
    return payload


def _manifest_entry_payload(
    entry: RawFieldManifestEntry | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(entry, RawFieldManifestEntry):
        return entry.to_payload()
    return dict(entry)


def _validate_required_fields(
    sidecar: Mapping[str, Any],
    issues: list[GlossaryProfileDiagnosticValidationIssue],
) -> None:
    for field in (
        "sidecar_schema_version",
        "diagnostic_scope",
        "access_boundary",
        "run_or_fixture_ref",
        "created_at",
        "source_language",
        "target_language",
        "translation_mode",
        "translation_snapshot_ref",
        "glossary_signature",
        "profile_signature",
        "raw_text_field_manifest",
        "secret_exclusion_policy",
        "retention_policy",
        "export_policy",
        "deletion_policy",
        "sections",
    ):
        if field not in sidecar:
            _add_issue(
                issues,
                GlossaryProfileDiagnosticValidationCode.MISSING_FIELD,
                field,
                f"{field} is required.",
            )


def _validate_access_boundary(
    boundary: object,
    issues: list[GlossaryProfileDiagnosticValidationIssue],
) -> None:
    if not isinstance(boundary, Mapping):
        _add_issue(
            issues,
            GlossaryProfileDiagnosticValidationCode.INVALID_ACCESS_BOUNDARY,
            "access_boundary",
            "access_boundary must be an object.",
        )
        return
    for key, expected in _REQUIRED_ACCESS_BOUNDARY.items():
        if boundary.get(key) != expected:
            _add_issue(
                issues,
                GlossaryProfileDiagnosticValidationCode.INVALID_ACCESS_BOUNDARY,
                f"access_boundary.{key}",
                f"access_boundary.{key} must be {expected!r}.",
            )


def _validate_tbd_policy(
    sidecar: Mapping[str, Any],
    field: str,
    issues: list[GlossaryProfileDiagnosticValidationIssue],
) -> None:
    if sidecar.get(field) != _TBD_POLICY:
        _add_issue(
            issues,
            GlossaryProfileDiagnosticValidationCode.INVALID_POLICY,
            field,
            f"{field} must remain TBD until a separate owner-approved policy.",
        )


def _validate_manifest(
    manifest: object,
    issues: list[GlossaryProfileDiagnosticValidationIssue],
) -> set[str]:
    manifest_paths: set[str] = set()
    if not isinstance(manifest, list):
        _add_issue(
            issues,
            GlossaryProfileDiagnosticValidationCode.INVALID_MANIFEST_ENTRY,
            "raw_text_field_manifest",
            "raw_text_field_manifest must be an array.",
        )
        return manifest_paths
    for index, entry in enumerate(manifest):
        path = f"raw_text_field_manifest[{index}]"
        if not isinstance(entry, Mapping):
            _add_issue(
                issues,
                GlossaryProfileDiagnosticValidationCode.INVALID_MANIFEST_ENTRY,
                path,
                "raw_text_field_manifest entries must be objects.",
            )
            continue
        entry_path = entry.get("path")
        if not isinstance(entry_path, str) or not entry_path:
            _add_issue(
                issues,
                GlossaryProfileDiagnosticValidationCode.INVALID_MANIFEST_ENTRY,
                f"{path}.path",
                "manifest entry path is required.",
            )
        else:
            manifest_paths.add(entry_path)
        if str(entry.get("classification")) not in {
            item.value for item in RawFieldClassification
        }:
            _add_issue(
                issues,
                GlossaryProfileDiagnosticValidationCode.INVALID_MANIFEST_ENTRY,
                f"{path}.classification",
                "manifest entry classification is not approved.",
            )
        if entry.get("required_boundary") != _OWNER_ONLY:
            _add_issue(
                issues,
                GlossaryProfileDiagnosticValidationCode.INVALID_MANIFEST_ENTRY,
                f"{path}.required_boundary",
                "manifest entry required_boundary must be owner_only.",
            )
        if entry.get("ordinary_surface_policy") != _FORBIDDEN:
            _add_issue(
                issues,
                GlossaryProfileDiagnosticValidationCode.INVALID_MANIFEST_ENTRY,
                f"{path}.ordinary_surface_policy",
                "manifest entry ordinary_surface_policy must be forbidden.",
            )
    return manifest_paths


def _iter_raw_capable_values(value: object, path: str):
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in _RAW_CAPABLE_FIELD_NAMES:
                yield child_path, child
            yield from _iter_raw_capable_values(child, child_path)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_raw_capable_values(child, f"{path}[]")


def _iter_secret_material_paths(value: object, path: str = ""):
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            lowered = key_text.lower()
            if child_path == "secret_exclusion_policy":
                continue
            if any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS):
                if child not in (None, "", "[redacted]"):
                    yield child_path
            yield from _iter_secret_material_paths(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_secret_material_paths(child, f"{path}[{index}]")
    elif isinstance(value, str) and any(
        pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS
    ):
        yield path


def _has_content(value: object) -> bool:
    return value not in (None, "", (), [], {})


def _section_counts(sections: object) -> dict[str, int]:
    if not isinstance(sections, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, value in sections.items():
        if isinstance(value, list):
            counts[str(key)] = len(value)
        elif isinstance(value, Mapping):
            counts[str(key)] = 1
        else:
            counts[str(key)] = int(value not in (None, "", (), []))
    return counts


def _add_issue(
    issues: list[GlossaryProfileDiagnosticValidationIssue],
    code: GlossaryProfileDiagnosticValidationCode,
    path: str,
    message: str,
) -> None:
    issues.append(
        GlossaryProfileDiagnosticValidationIssue(
            code=code,
            path=path,
            message=message,
        )
    )
