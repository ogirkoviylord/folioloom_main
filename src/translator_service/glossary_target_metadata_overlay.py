from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossarySnapshot,
)

GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION = (
    "glossary-runtime-target-metadata-fixture-v1"
)
GLOSSARY_TARGET_METADATA_OVERLAY_POLICY = (
    "local_owner_only_approved_epub_target_metadata_overlay_v1"
)

_DEFAULT_MAX_ENTRIES_PER_TARGET = 128
_DEFAULT_MAX_ALIASES = 8
_DEFAULT_MAX_TARGET_VARIANTS = 8
_DEFAULT_MAX_FORBIDDEN_VARIANTS = 8
_DEFAULT_MAX_MORPHOLOGY_NOTES = 4
_DEFAULT_MAX_FIELD_CHARS = 160

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "fixture_id",
        "overlay_id",
        "input_path",
        "input_id",
        "source_language",
        "scope",
        "owner_approved",
        "targets",
    }
)
_TARGET_KEYS = frozenset({"entries"})
_ENTRY_KEYS = frozenset(
    {
        "entry_id",
        "source_canonical",
        "aliases",
        "source_evidence_ids",
        "target_canonical",
        "target_variants",
        "forbidden_variants",
        "morphology_notes",
        "terminology_policy_metadata",
        "policy_id",
        "policy_version",
        "match_mode",
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
        "passage",
        "passage_text",
        "prompt",
        "prompt_body",
        "prompt_messages",
        "provider_request",
        "provider_response",
        "raw_excerpt",
        "raw_passage",
        "raw_passages",
        "raw_prompt",
        "raw_source",
        "raw_source_text",
        "request_body",
        "response_body",
        "source_excerpt",
        "source_passage",
        "source_text",
        "target_text",
        "translated_text",
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
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9:._/-]+")


@dataclass(frozen=True)
class GlossaryTargetMetadataOverlayConfig:
    enabled: bool = False
    max_entries_per_target: int = _DEFAULT_MAX_ENTRIES_PER_TARGET
    max_aliases: int = _DEFAULT_MAX_ALIASES
    max_target_variants: int = _DEFAULT_MAX_TARGET_VARIANTS
    max_forbidden_variants: int = _DEFAULT_MAX_FORBIDDEN_VARIANTS
    max_morphology_notes: int = _DEFAULT_MAX_MORPHOLOGY_NOTES
    max_field_chars: int = _DEFAULT_MAX_FIELD_CHARS


@dataclass(frozen=True)
class GlossaryTargetMetadataOverlayResult:
    snapshot: GlossarySnapshot
    status: str
    reason_codes: tuple[str, ...]
    target_language: str
    overlay_id: str = "Unknown"
    overlay_signature: str = "Unknown"
    overlay_entry_count: int = 0
    matched_entry_count: int = 0
    unmatched_entry_count: int = 0

    @property
    def metadata(self) -> dict[str, Any]:
        return glossary_target_metadata_overlay_metadata(self)


def load_glossary_target_metadata_overlay(
    path: Path,
    *,
    snapshot: GlossarySnapshot,
    target_language: str,
    config: GlossaryTargetMetadataOverlayConfig | None = None,
) -> GlossaryTargetMetadataOverlayResult:
    config = config or GlossaryTargetMetadataOverlayConfig()
    if not config.enabled:
        return _result(
            snapshot,
            status="disabled",
            reason_codes=("target_metadata_overlay_disabled",),
            target_language=target_language,
        )
    if not path.is_file():
        return _result(
            snapshot,
            status="missing",
            reason_codes=("target_metadata_overlay_missing",),
            target_language=target_language,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _result(
            snapshot,
            status="invalid",
            reason_codes=("target_metadata_overlay_unreadable",),
            target_language=target_language,
        )
    return apply_glossary_target_metadata_overlay(
        snapshot,
        payload,
        target_language=target_language,
        config=config,
    )


def apply_glossary_target_metadata_overlay(
    snapshot: GlossarySnapshot,
    payload: Any,
    *,
    target_language: str,
    config: GlossaryTargetMetadataOverlayConfig | None = None,
) -> GlossaryTargetMetadataOverlayResult:
    config = config or GlossaryTargetMetadataOverlayConfig()
    if not config.enabled:
        return _result(
            snapshot,
            status="disabled",
            reason_codes=("target_metadata_overlay_disabled",),
            target_language=target_language,
        )
    if _language_key(snapshot.target_language) != _language_key(target_language):
        return _result(
            snapshot,
            status="invalid",
            reason_codes=("target_metadata_overlay_snapshot_target_mismatch",),
            target_language=target_language,
        )

    overlay_entries, reason_codes = _overlay_entries(
        payload,
        target_language=target_language,
        config=config,
    )
    overlay_id = _overlay_id(payload)
    if reason_codes:
        return _result(
            snapshot,
            status="invalid",
            reason_codes=reason_codes,
            target_language=target_language,
            overlay_id=overlay_id,
        )

    overlaid_snapshot, matched_count = _overlay_snapshot_entries(
        snapshot,
        overlay_entries,
    )
    if matched_count == 0:
        return _result(
            snapshot,
            status="loaded_no_matches",
            reason_codes=("target_metadata_overlay_no_matching_retained_entries",),
            target_language=target_language,
            overlay_id=overlay_id,
            overlay_signature=_overlay_signature(payload, target_language),
            overlay_entry_count=len(overlay_entries),
            unmatched_entry_count=len(overlay_entries),
        )
    return _result(
        overlaid_snapshot,
        status="applied",
        reason_codes=(),
        target_language=target_language,
        overlay_id=overlay_id,
        overlay_signature=_overlay_signature(payload, target_language),
        overlay_entry_count=len(overlay_entries),
        matched_entry_count=matched_count,
        unmatched_entry_count=max(0, len(overlay_entries) - matched_count),
    )


def glossary_target_metadata_overlay_metadata(
    result: GlossaryTargetMetadataOverlayResult,
) -> dict[str, Any]:
    return {
        "schema_version": GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
        "policy": GLOSSARY_TARGET_METADATA_OVERLAY_POLICY,
        "status": result.status,
        "reason_codes": list(result.reason_codes),
        "overlay_id": _safe_id(result.overlay_id),
        "overlay_signature": result.overlay_signature,
        "target_language": result.target_language or "Unknown",
        "overlay_entry_count": result.overlay_entry_count,
        "matched_entry_count": result.matched_entry_count,
        "unmatched_entry_count": result.unmatched_entry_count,
        "metadata_only": True,
        "raw_payload_included": False,
        "normal_translation_prompts_changed": False,
        "live_provider_calls_allowed": False,
        "durable_state_mutation_allowed": False,
        "cache_mutation_allowed": False,
    }


def _overlay_entries(
    payload: Any,
    *,
    target_language: str,
    config: GlossaryTargetMetadataOverlayConfig,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[str, ...]]:
    reason_codes: list[str] = []
    if not isinstance(payload, Mapping):
        return (), ("target_metadata_overlay_not_object",)
    reason_codes.extend(_unsafe_payload_reason_codes(payload))
    if (
        payload.get("schema_version")
        != GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION
    ):
        reason_codes.append("target_metadata_overlay_schema_invalid")
    if not payload.get("owner_approved"):
        reason_codes.append("target_metadata_overlay_owner_approval_missing")
    if set(payload) - _TOP_LEVEL_KEYS:
        reason_codes.append("target_metadata_overlay_unsupported_field")

    targets = payload.get("targets")
    if not isinstance(targets, Mapping):
        reason_codes.append("target_metadata_overlay_targets_invalid")
        return (), _unique_reasons(reason_codes)

    target_payload = targets.get(target_language)
    if not isinstance(target_payload, Mapping):
        reason_codes.append("target_metadata_overlay_target_missing")
        return (), _unique_reasons(reason_codes)
    if set(target_payload) - _TARGET_KEYS:
        reason_codes.append("target_metadata_overlay_unsupported_target_field")

    raw_entries = target_payload.get("entries")
    if isinstance(raw_entries, (str, bytes)) or not isinstance(raw_entries, Sequence):
        reason_codes.append("target_metadata_overlay_entries_invalid")
        return (), _unique_reasons(reason_codes)
    if not raw_entries:
        reason_codes.append("target_metadata_overlay_entries_empty")
    if len(raw_entries) > config.max_entries_per_target:
        reason_codes.append("target_metadata_overlay_entry_limit_exceeded")

    entries: list[Mapping[str, Any]] = []
    for raw_entry in raw_entries:
        entry, entry_reasons = _overlay_entry(raw_entry, config=config)
        reason_codes.extend(entry_reasons)
        if entry is not None:
            entries.append(entry)

    return tuple(entries), _unique_reasons(reason_codes)


def _overlay_entry(
    raw_entry: Any,
    *,
    config: GlossaryTargetMetadataOverlayConfig,
) -> tuple[Mapping[str, Any] | None, tuple[str, ...]]:
    reason_codes: list[str] = []
    if not isinstance(raw_entry, Mapping):
        return None, ("target_metadata_overlay_entry_invalid",)
    if set(raw_entry) - _ENTRY_KEYS:
        reason_codes.append("target_metadata_overlay_unsupported_entry_field")

    source_canonical = _text_field(raw_entry.get("source_canonical"), config=config)
    aliases = _text_sequence(
        raw_entry.get("aliases"),
        limit=config.max_aliases,
        config=config,
    )
    target_canonical = _text_field(raw_entry.get("target_canonical"), config=config)
    target_variants = _text_sequence(
        raw_entry.get("target_variants"),
        limit=config.max_target_variants,
        config=config,
    )
    forbidden_variants = _text_sequence(
        raw_entry.get("forbidden_variants"),
        limit=config.max_forbidden_variants,
        config=config,
    )
    morphology_notes = _text_sequence(
        raw_entry.get("morphology_notes"),
        limit=config.max_morphology_notes,
        config=config,
    )

    if source_canonical is None:
        reason_codes.append("target_metadata_overlay_source_missing")
    if target_canonical is None and not target_variants:
        reason_codes.append("target_metadata_overlay_target_missing")
    if _sequence_over_limit(raw_entry.get("aliases"), limit=config.max_aliases):
        reason_codes.append("target_metadata_overlay_alias_limit_exceeded")
    if _sequence_over_limit(
        raw_entry.get("target_variants"),
        limit=config.max_target_variants,
    ):
        reason_codes.append("target_metadata_overlay_variant_limit_exceeded")
    if _sequence_over_limit(
        raw_entry.get("forbidden_variants"),
        limit=config.max_forbidden_variants,
    ):
        reason_codes.append("target_metadata_overlay_forbidden_limit_exceeded")
    if _sequence_over_limit(
        raw_entry.get("morphology_notes"),
        limit=config.max_morphology_notes,
    ):
        reason_codes.append("target_metadata_overlay_morphology_limit_exceeded")
    if _policy_metadata_invalid(raw_entry.get("terminology_policy_metadata")):
        reason_codes.append("target_metadata_overlay_policy_metadata_invalid")

    if reason_codes or source_canonical is None:
        return None, _unique_reasons(reason_codes)

    return {
        "source_canonical": source_canonical,
        "aliases": aliases,
        "target_canonical": target_canonical,
        "target_variants": target_variants,
        "forbidden_variants": forbidden_variants,
        "morphology_notes": morphology_notes,
    }, ()


def _overlay_snapshot_entries(
    snapshot: GlossarySnapshot,
    overlay_entries: Sequence[Mapping[str, Any]],
) -> tuple[GlossarySnapshot, int]:
    overlay_by_source_key: dict[str, Mapping[str, Any]] = {}
    for overlay_entry in overlay_entries:
        for term in _overlay_entry_source_terms(overlay_entry):
            overlay_by_source_key.setdefault(_term_key(term), overlay_entry)

    matched_count = 0
    overlaid_entries: list[GlossaryEntry] = []
    for entry in snapshot.entries:
        overlay_entry = _matching_overlay_entry(entry, overlay_by_source_key)
        if overlay_entry is None:
            overlaid_entries.append(entry)
            continue
        matched_count += 1
        overlaid_entries.append(
            replace(
                entry,
                target_canonical=overlay_entry.get("target_canonical") or None,
                target_variants=tuple(overlay_entry.get("target_variants") or ()),
                forbidden_variants=tuple(
                    overlay_entry.get("forbidden_variants") or ()
                ),
                morphology_notes=tuple(overlay_entry.get("morphology_notes") or ()),
            )
        )
    if matched_count == 0:
        return snapshot, 0
    return replace(snapshot, entries=tuple(overlaid_entries)), matched_count


def _matching_overlay_entry(
    entry: GlossaryEntry,
    overlay_by_source_key: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for term in _entry_source_terms(entry):
        match = overlay_by_source_key.get(_term_key(term))
        if match is not None:
            return match
    return None


def _overlay_entry_source_terms(entry: Mapping[str, Any]) -> tuple[str, ...]:
    terms = [str(entry["source_canonical"])]
    terms.extend(str(alias) for alias in entry.get("aliases") or ())
    return tuple(dict.fromkeys(term for term in terms if term.strip()))


def _entry_source_terms(entry: GlossaryEntry) -> tuple[str, ...]:
    terms = [entry.source_canonical]
    terms.extend(entry.aliases)
    return tuple(dict.fromkeys(term for term in terms if term.strip()))


def _term_key(term: str) -> str:
    return " ".join(term.casefold().split())


def _language_key(language: str) -> str:
    return language.strip().casefold()


def _text_field(
    value: Any,
    *,
    config: GlossaryTargetMetadataOverlayConfig,
) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text or len(text) > config.max_field_chars:
        return None
    if text in {"TBD", "Unknown"}:
        return None
    if _string_contains_secret_material(text):
        return None
    return text


def _text_sequence(
    value: Any,
    *,
    limit: int,
    config: GlossaryTargetMetadataOverlayConfig,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    result: list[str] = []
    for item in value[:limit]:
        text = _text_field(item, config=config)
        if text is not None:
            result.append(text)
    return tuple(dict.fromkeys(result))


def _sequence_over_limit(value: Any, *, limit: int) -> bool:
    return (
        not isinstance(value, (str, bytes))
        and isinstance(value, Sequence)
        and len(value) > limit
    )


def _policy_metadata_invalid(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, Mapping):
        return True
    if set(value) - _POLICY_METADATA_KEYS:
        return True
    for item in value.values():
        if not isinstance(item, str) or not item.strip():
            return True
        if _string_contains_secret_material(item):
            return True
    return False


def _unsafe_payload_reason_codes(value: Any) -> list[str]:
    reasons: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold()
            flat_key = re.sub(r"[^a-z0-9]+", "", normalized)
            if normalized in _RAW_KEYS or flat_key in _RAW_KEY_ALIASES:
                reasons.append("target_metadata_overlay_raw_field_present")
            env_like_key = normalized.startswith(".env") or flat_key.startswith(
                ("dotenv", "env")
            )
            if (
                normalized in _SECRET_KEYS
                or flat_key in _SECRET_KEY_ALIASES
                or env_like_key
                or flat_key.endswith(("key", "token", "password", "secret", "dsn"))
            ):
                reasons.append("target_metadata_overlay_secret_field_present")
            reasons.extend(_unsafe_payload_reason_codes(item))
        return reasons
    if isinstance(value, str) and _string_contains_secret_material(value):
        return ["target_metadata_overlay_secret_material_present"]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            reasons.extend(_unsafe_payload_reason_codes(item))
    return reasons


def _string_contains_secret_material(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def _overlay_id(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return "Unknown"
    return _safe_id(payload.get("overlay_id") or payload.get("fixture_id"))


def _overlay_signature(payload: Any, target_language: str) -> str:
    if not isinstance(payload, Mapping):
        return "Unknown"
    targets = payload.get("targets", {})
    target_entries = (
        targets.get(target_language, {}).get("entries", ())
        if isinstance(targets, Mapping)
        else ()
    )
    digest_payload = {
        "schema_version": GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
        "overlay_id": payload.get("overlay_id") or payload.get("fixture_id"),
        "target_language": target_language,
        "entries": target_entries,
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"target-metadata-overlay:v1:{digest}"


def _result(
    snapshot: GlossarySnapshot,
    *,
    status: str,
    reason_codes: Sequence[str],
    target_language: str,
    overlay_id: str = "Unknown",
    overlay_signature: str = "Unknown",
    overlay_entry_count: int = 0,
    matched_entry_count: int = 0,
    unmatched_entry_count: int = 0,
) -> GlossaryTargetMetadataOverlayResult:
    return GlossaryTargetMetadataOverlayResult(
        snapshot=snapshot,
        status=status,
        reason_codes=_unique_reasons(reason_codes),
        target_language=target_language,
        overlay_id=_safe_id(overlay_id),
        overlay_signature=overlay_signature,
        overlay_entry_count=overlay_entry_count,
        matched_entry_count=matched_entry_count,
        unmatched_entry_count=unmatched_entry_count,
    )


def _safe_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Unknown"
    return _SAFE_ID_RE.sub("_", value.strip())[:128] or "Unknown"


def _unique_reasons(reason_codes: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(reason_codes)))
