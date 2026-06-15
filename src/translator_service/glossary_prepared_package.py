from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from translator_service.glossary_target_metadata_overlay import (
    GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
)

GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION = "glossary-prepared-package-v1"
GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID = "deepseek-pro-glossary-prep-v1"
GLOSSARY_PREPARED_PACKAGE_OVERLAY_SCOPE = (
    "local_owner_only_prepared_glossary_package_v1"
)

_DEFAULT_MAX_ENTRIES = 128
_DEFAULT_MAX_ALIASES = 8
_DEFAULT_MAX_TARGET_VARIANTS = 8
_DEFAULT_MAX_FORBIDDEN_VARIANTS = 8
_DEFAULT_MAX_EVIDENCE_REFS = 16
_DEFAULT_MAX_REASON_CODES = 16
_DEFAULT_MAX_FIELD_CHARS = 180

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "package_id",
        "source_language",
        "target_language",
        "glossary_mode",
        "provider_role_id",
        "provider_model",
        "provider_run_id",
        "diagnostics_ref",
        "source_document_fingerprint",
        "candidate_selector_signature",
        "glossary_snapshot_signature",
        "language_policy_package_id",
        "language_policy_package_version",
        "owner_approved",
        "entries",
    }
)
_ENTRY_KEYS = frozenset(
    {
        "source_entry_id",
        "source_canonical",
        "aliases",
        "evidence_refs",
        "source_unit_refs",
        "source_block_refs",
        "target_canonical",
        "target_variants",
        "forbidden_variants",
        "strategy",
        "confidence",
        "needs_review",
        "issue_codes",
        "reason_codes",
        "terminology_policy_metadata",
    }
)
_POLICY_METADATA_KEYS = frozenset(
    {
        "policy_id",
        "policy_version",
        "terminology_policy_id",
        "terminology_policy_version",
        "match_mode",
        "mode",
        "package_id",
        "package_version",
        "signature",
    }
)
_RAW_KEYS = frozenset(
    {
        "api_key",
        "auth_material",
        "authorization",
        "bounded_source_excerpt",
        "excerpt",
        "message",
        "messages",
        "passage",
        "passage_text",
        "prompt",
        "prompt_body",
        "prompt_messages",
        "provider_request",
        "provider_response",
        "raw_excerpt",
        "raw_output",
        "raw_passage",
        "raw_passages",
        "raw_prompt",
        "raw_provider_response",
        "raw_source",
        "raw_source_text",
        "request_body",
        "response_body",
        "source_excerpt",
        "source_passage",
        "source_text",
        "target_text",
        "translated_text",
        "translation",
        "translation_text",
    }
)
_SECRET_KEYS = frozenset(
    {
        ".env",
        "bearer",
        "dsn",
        "env",
        "key",
        "password",
        "secret",
        "token",
    }
)
_RAW_KEY_ALIASES = frozenset(re.sub(r"[^a-z0-9]+", "", key) for key in _RAW_KEYS)
_SECRET_KEY_ALIASES = frozenset(
    re.sub(r"[^a-z0-9]+", "", key) for key in _SECRET_KEYS
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
    re.compile(r"Authorization\s*:", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[A-Z0-9_]*(API_KEY|TOKEN|PASSWORD|SECRET|DSN)\s*="),
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
)


@dataclass(frozen=True)
class PreparedGlossaryPackageConfig:
    max_entries: int = _DEFAULT_MAX_ENTRIES
    max_aliases: int = _DEFAULT_MAX_ALIASES
    max_target_variants: int = _DEFAULT_MAX_TARGET_VARIANTS
    max_forbidden_variants: int = _DEFAULT_MAX_FORBIDDEN_VARIANTS
    max_evidence_refs: int = _DEFAULT_MAX_EVIDENCE_REFS
    max_reason_codes: int = _DEFAULT_MAX_REASON_CODES
    max_field_chars: int = _DEFAULT_MAX_FIELD_CHARS


@dataclass(frozen=True)
class PreparedGlossaryEntry:
    source_entry_id: str
    source_canonical: str
    aliases: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    target_canonical: str | None
    target_variants: tuple[str, ...]
    forbidden_variants: tuple[str, ...]
    strategy: str
    confidence: float
    needs_review: bool
    reason_codes: tuple[str, ...]
    terminology_policy_metadata: Mapping[str, str]


@dataclass(frozen=True)
class PreparedGlossaryPackage:
    package_id: str
    source_language: str
    target_language: str
    provider_role_id: str
    provider_model: str
    provider_run_id: str
    candidate_selector_signature: str
    entries: tuple[PreparedGlossaryEntry, ...]
    glossary_mode: str = "with_glossary"
    diagnostics_ref: str = "Unknown"
    source_document_fingerprint: str = "Unknown"
    glossary_snapshot_signature: str = "Unknown"
    language_policy_package_id: str = "Unknown"
    language_policy_package_version: str = "Unknown"
    schema_version: str = GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION

    def to_target_metadata_overlay_payload(self) -> dict[str, Any]:
        return {
            "schema_version": GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
            "overlay_id": self.package_id,
            "scope": GLOSSARY_PREPARED_PACKAGE_OVERLAY_SCOPE,
            "owner_approved": True,
            "source_language": self.source_language,
            "targets": {
                self.target_language: {
                    "entries": [
                        _entry_to_overlay_payload(entry) for entry in self.entries
                    ]
                }
            },
        }


@dataclass(frozen=True)
class PreparedGlossaryPackageValidationResult:
    status: str
    reason_codes: tuple[str, ...]
    package: PreparedGlossaryPackage | None = None
    package_id: str = "Unknown"
    package_signature: str = "Unknown"
    source_language: str = "Unknown"
    target_language: str = "Unknown"
    provider_role_id: str = "Unknown"
    provider_model: str = "Unknown"
    entry_count: int = 0
    ready_entry_count: int = 0
    needs_review_entry_count: int = 0

    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.package is not None

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
            "metadata_only": True,
            "raw_payload_included": False,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "package_id": self.package_id,
            "package_signature": self.package_signature,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "provider_role_id": self.provider_role_id,
            "provider_model": self.provider_model,
            "entry_count": self.entry_count,
            "ready_entry_count": self.ready_entry_count,
            "needs_review_entry_count": self.needs_review_entry_count,
        }


def validate_prepared_glossary_package(
    payload: Any,
    *,
    target_language: str | None = None,
    config: PreparedGlossaryPackageConfig | None = None,
) -> PreparedGlossaryPackageValidationResult:
    config = config or PreparedGlossaryPackageConfig()
    if not isinstance(payload, Mapping):
        return _invalid(("prepared_glossary_package_not_object",))

    safety_reasons = _unsafe_payload_reasons(payload)
    if safety_reasons:
        return _invalid(
            safety_reasons,
            package_id=_package_id(payload),
            target_language=_text_value(payload.get("target_language"), "Unknown"),
            provider_role_id=_text_value(payload.get("provider_role_id"), "Unknown"),
            provider_model=_text_value(payload.get("provider_model"), "Unknown"),
        )

    reason_codes: list[str] = []
    unsupported = _unsupported_keys(payload, _TOP_LEVEL_KEYS)
    if unsupported:
        reason_codes.append("prepared_glossary_package_unsupported_field")
    if payload.get("schema_version") != GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION:
        reason_codes.append("prepared_glossary_package_schema_invalid")
    if payload.get("owner_approved") is not True:
        reason_codes.append("prepared_glossary_package_owner_approval_missing")

    package_id = _required_text(
        payload,
        "package_id",
        reason_codes,
        "prepared_glossary_package_id_missing",
        config=config,
    )
    source_language = _required_text(
        payload,
        "source_language",
        reason_codes,
        "prepared_glossary_package_source_language_missing",
        config=config,
    )
    package_target = _required_text(
        payload,
        "target_language",
        reason_codes,
        "prepared_glossary_package_target_language_missing",
        config=config,
    )
    if target_language is not None and _language_key(package_target) != _language_key(
        target_language
    ):
        reason_codes.append("prepared_glossary_package_target_mismatch")
    glossary_mode = _text_value(payload.get("glossary_mode"), "with_glossary")
    if glossary_mode != "with_glossary":
        reason_codes.append("prepared_glossary_package_mode_invalid")

    provider_role_id = _required_text(
        payload,
        "provider_role_id",
        reason_codes,
        "prepared_glossary_package_provider_role_missing",
        config=config,
    )
    if (
        provider_role_id
        and provider_role_id != GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID
    ):
        reason_codes.append("prepared_glossary_package_provider_role_invalid")
    provider_model = _required_text(
        payload,
        "provider_model",
        reason_codes,
        "prepared_glossary_package_provider_model_missing",
        config=config,
    )
    candidate_selector_signature = _required_text(
        payload,
        "candidate_selector_signature",
        reason_codes,
        "prepared_glossary_package_selector_signature_missing",
        config=config,
    )

    entries_payload = payload.get("entries")
    entries: list[PreparedGlossaryEntry] = []
    entry_reasons: list[str] = []
    if not isinstance(entries_payload, Sequence) or isinstance(
        entries_payload, (str, bytes, bytearray)
    ):
        entry_reasons.append("prepared_glossary_package_entries_invalid")
    elif not entries_payload:
        entry_reasons.append("prepared_glossary_package_entries_empty")
    elif len(entries_payload) > config.max_entries:
        entry_reasons.append("prepared_glossary_package_entry_limit_exceeded")
    else:
        for raw_entry in entries_payload:
            entry, reasons = _prepared_entry(raw_entry, config=config)
            if entry is None:
                entry_reasons.extend(reasons)
            else:
                entries.append(entry)
                entry_reasons.extend(reasons)

    reason_codes.extend(_dedupe(entry_reasons))

    if reason_codes:
        return _invalid(
            reason_codes,
            package_id=package_id or _package_id(payload),
            source_language=source_language or "Unknown",
            target_language=package_target or "Unknown",
            provider_role_id=provider_role_id or "Unknown",
            provider_model=provider_model or "Unknown",
            entry_count=len(entries),
            needs_review_entry_count=sum(1 for entry in entries if entry.needs_review),
        )

    needs_review_count = sum(1 for entry in entries if entry.needs_review)
    package = PreparedGlossaryPackage(
        package_id=package_id,
        source_language=source_language,
        target_language=package_target,
        glossary_mode=glossary_mode,
        provider_role_id=provider_role_id,
        provider_model=provider_model,
        provider_run_id=_text_value(payload.get("provider_run_id"), "Unknown"),
        diagnostics_ref=_text_value(payload.get("diagnostics_ref"), "Unknown"),
        source_document_fingerprint=_text_value(
            payload.get("source_document_fingerprint"),
            "Unknown",
        ),
        candidate_selector_signature=candidate_selector_signature,
        glossary_snapshot_signature=_text_value(
            payload.get("glossary_snapshot_signature"),
            "Unknown",
        ),
        language_policy_package_id=_text_value(
            payload.get("language_policy_package_id"),
            "Unknown",
        ),
        language_policy_package_version=_text_value(
            payload.get("language_policy_package_version"),
            "Unknown",
        ),
        entries=tuple(entries),
    )
    if needs_review_count:
        return _result(
            status="needs_review",
            reason_codes=("prepared_glossary_package_needs_review",),
            package=package,
            package_signature=_package_signature(payload),
            entry_count=len(entries),
            ready_entry_count=0,
            needs_review_entry_count=needs_review_count,
        )
    return _result(
        status="ready",
        reason_codes=(),
        package=package,
        package_signature=_package_signature(payload),
        entry_count=len(entries),
        ready_entry_count=len(entries),
        needs_review_entry_count=0,
    )


def _prepared_entry(
    payload: Any,
    *,
    config: PreparedGlossaryPackageConfig,
) -> tuple[PreparedGlossaryEntry | None, tuple[str, ...]]:
    if not isinstance(payload, Mapping):
        return None, ("prepared_glossary_package_entry_invalid",)
    safety_reasons = _unsafe_payload_reasons(payload)
    if safety_reasons:
        return None, safety_reasons

    reason_codes: list[str] = []
    if _unsupported_keys(payload, _ENTRY_KEYS):
        reason_codes.append("prepared_glossary_package_entry_unsupported_field")
    source_entry_id = _required_text(
        payload,
        "source_entry_id",
        reason_codes,
        "prepared_glossary_package_source_entry_id_missing",
        config=config,
    )
    source_canonical = _required_text(
        payload,
        "source_canonical",
        reason_codes,
        "prepared_glossary_package_source_missing",
        config=config,
    )
    evidence_refs = _string_tuple(
        payload.get("evidence_refs"),
        max_items=config.max_evidence_refs,
        max_chars=config.max_field_chars,
        invalid_code="prepared_glossary_package_evidence_refs_invalid",
        limit_code="prepared_glossary_package_evidence_ref_limit_exceeded",
        reason_codes=reason_codes,
    )
    if not evidence_refs:
        reason_codes.append("prepared_glossary_package_evidence_missing")

    aliases = _string_tuple(
        payload.get("aliases", ()),
        max_items=config.max_aliases,
        max_chars=config.max_field_chars,
        invalid_code="prepared_glossary_package_aliases_invalid",
        limit_code="prepared_glossary_package_alias_limit_exceeded",
        reason_codes=reason_codes,
    )
    target_canonical = _optional_text(payload.get("target_canonical"), config=config)
    target_variants = _string_tuple(
        payload.get("target_variants", ()),
        max_items=config.max_target_variants,
        max_chars=config.max_field_chars,
        invalid_code="prepared_glossary_package_target_variants_invalid",
        limit_code="prepared_glossary_package_target_variant_limit_exceeded",
        reason_codes=reason_codes,
    )
    forbidden_variants = _string_tuple(
        payload.get("forbidden_variants", ()),
        max_items=config.max_forbidden_variants,
        max_chars=config.max_field_chars,
        invalid_code="prepared_glossary_package_forbidden_variants_invalid",
        limit_code="prepared_glossary_package_forbidden_variant_limit_exceeded",
        reason_codes=reason_codes,
    )
    if target_canonical is None and not target_variants:
        reason_codes.append("prepared_glossary_package_target_missing")

    confidence = payload.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not (0 <= float(confidence) <= 1)
    ):
        reason_codes.append("prepared_glossary_package_confidence_invalid")
        confidence_value = 0.0
    else:
        confidence_value = float(confidence)
    needs_review = payload.get("needs_review", False)
    if not isinstance(needs_review, bool):
        reason_codes.append("prepared_glossary_package_needs_review_invalid")
        needs_review = True

    entry_reason_codes = _string_tuple(
        payload.get("reason_codes", payload.get("issue_codes", ())),
        max_items=config.max_reason_codes,
        max_chars=config.max_field_chars,
        invalid_code="prepared_glossary_package_reason_codes_invalid",
        limit_code="prepared_glossary_package_reason_code_limit_exceeded",
        reason_codes=reason_codes,
    )
    policy_metadata, policy_reasons = _policy_metadata(payload)
    reason_codes.extend(policy_reasons)

    if reason_codes:
        return None, tuple(_dedupe(reason_codes))
    return (
        PreparedGlossaryEntry(
            source_entry_id=source_entry_id,
            source_canonical=source_canonical,
            aliases=aliases,
            evidence_refs=evidence_refs,
            target_canonical=target_canonical,
            target_variants=target_variants,
            forbidden_variants=forbidden_variants,
            strategy=_text_value(payload.get("strategy"), "unknown"),
            confidence=confidence_value,
            needs_review=bool(needs_review),
            reason_codes=entry_reason_codes,
            terminology_policy_metadata=policy_metadata,
        ),
        tuple(_dedupe(reason_codes)),
    )


def _entry_to_overlay_payload(entry: PreparedGlossaryEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entry_id": entry.source_entry_id,
        "source_canonical": entry.source_canonical,
        "aliases": list(entry.aliases),
        "source_evidence_ids": list(entry.evidence_refs),
        "target_canonical": entry.target_canonical,
        "target_variants": list(entry.target_variants),
        "forbidden_variants": list(entry.forbidden_variants),
    }
    if entry.terminology_policy_metadata:
        payload["terminology_policy_metadata"] = dict(
            entry.terminology_policy_metadata
        )
    return payload


def _policy_metadata(payload: Mapping[str, Any]) -> tuple[Mapping[str, str], list[str]]:
    policy_payload = payload.get("terminology_policy_metadata", {})
    if not isinstance(policy_payload, Mapping):
        return {}, ["prepared_glossary_package_policy_metadata_invalid"]
    reasons: list[str] = []
    if _unsupported_keys(policy_payload, _POLICY_METADATA_KEYS):
        reasons.append("prepared_glossary_package_policy_metadata_unsupported_field")
    values: dict[str, str] = {}
    for key, value in policy_payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            reasons.append("prepared_glossary_package_policy_metadata_invalid")
            continue
        stripped = value.strip()
        if stripped:
            values[key] = stripped
    return values, reasons


def _string_tuple(
    value: Any,
    *,
    max_items: int,
    max_chars: int,
    invalid_code: str,
    limit_code: str,
    reason_codes: list[str],
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        reason_codes.append(invalid_code)
        return ()
    if len(value) > max_items:
        reason_codes.append(limit_code)
        return ()
    items: list[str] = []
    for item in value:
        item_config = PreparedGlossaryPackageConfig(max_field_chars=max_chars)
        text = _optional_text(item, config=item_config)
        if text is None:
            reason_codes.append(invalid_code)
            continue
        items.append(text)
    return tuple(items)


def _required_text(
    payload: Mapping[str, Any],
    key: str,
    reason_codes: list[str],
    missing_code: str,
    *,
    config: PreparedGlossaryPackageConfig,
) -> str:
    text = _optional_text(payload.get(key), config=config)
    if text is None:
        reason_codes.append(missing_code)
        return ""
    return text


def _optional_text(
    value: Any,
    *,
    config: PreparedGlossaryPackageConfig,
) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > config.max_field_chars:
        return None
    return text


def _text_value(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    text = value.strip()
    return text or default


def _invalid(
    reason_codes: Sequence[str],
    *,
    package_id: str = "Unknown",
    source_language: str = "Unknown",
    target_language: str = "Unknown",
    provider_role_id: str = "Unknown",
    provider_model: str = "Unknown",
    entry_count: int = 0,
    needs_review_entry_count: int = 0,
) -> PreparedGlossaryPackageValidationResult:
    return PreparedGlossaryPackageValidationResult(
        status="invalid",
        reason_codes=tuple(_dedupe(reason_codes)),
        package_id=package_id,
        source_language=source_language,
        target_language=target_language,
        provider_role_id=provider_role_id,
        provider_model=provider_model,
        entry_count=entry_count,
        ready_entry_count=0,
        needs_review_entry_count=needs_review_entry_count,
    )


def _result(
    *,
    status: str,
    reason_codes: Sequence[str],
    package: PreparedGlossaryPackage,
    package_signature: str,
    entry_count: int,
    ready_entry_count: int,
    needs_review_entry_count: int,
) -> PreparedGlossaryPackageValidationResult:
    return PreparedGlossaryPackageValidationResult(
        status=status,
        reason_codes=tuple(_dedupe(reason_codes)),
        package=package,
        package_id=package.package_id,
        package_signature=package_signature,
        source_language=package.source_language,
        target_language=package.target_language,
        provider_role_id=package.provider_role_id,
        provider_model=package.provider_model,
        entry_count=entry_count,
        ready_entry_count=ready_entry_count,
        needs_review_entry_count=needs_review_entry_count,
    )


def _unsafe_payload_reasons(payload: Any) -> tuple[str, ...]:
    reasons: list[str] = []

    def visit(value: Any, path_key: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                key_alias = re.sub(r"[^a-z0-9]+", "", key_text.lower())
                if key_alias in _RAW_KEY_ALIASES:
                    reasons.append("prepared_glossary_package_raw_field_present")
                if _is_secret_key_alias(key_alias):
                    reasons.append("prepared_glossary_package_secret_field_present")
                visit(child, key_text)
        elif isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            for child in value:
                visit(child, path_key)
        elif isinstance(value, str):
            if _looks_secret(value):
                reasons.append("prepared_glossary_package_secret_material_present")

    visit(payload)
    return tuple(_dedupe(reasons))


def _looks_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def _is_secret_key_alias(key_alias: str) -> bool:
    if key_alias in _SECRET_KEY_ALIASES:
        return True
    if key_alias.startswith("env"):
        return True
    secret_suffixes = (
        "apikey",
        "authorization",
        "authtoken",
        "dsn",
        "password",
        "refreshtoken",
        "secret",
        "token",
    )
    return key_alias.endswith(secret_suffixes)


def _unsupported_keys(
    payload: Mapping[str, Any],
    allowed: frozenset[str],
) -> tuple[str, ...]:
    return tuple(str(key) for key in payload if str(key) not in allowed)


def _package_id(payload: Mapping[str, Any]) -> str:
    return _text_value(payload.get("package_id"), "Unknown")


def _package_signature(payload: Mapping[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"prepared-glossary-package:v1:{digest[:16]}"


def _language_key(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
