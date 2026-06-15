from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from translator_service.deepseek_client import DeepSeekClient, Transport
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.glossary_prepared_prep_service import (
    DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
    PreparedGlossaryProviderRequest,
    PreparedGlossaryProviderResponse,
)


@dataclass(frozen=True)
class PreparedGlossaryDeepSeekProviderConfig:
    provider_model: str = DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL


class PreparedGlossaryChatClient(Protocol):
    def create_chat_completion(
        self,
        *,
        system_prompt: str,
        user_text: str,
        response_format: dict[str, str] | None = None,
        allow_empty_content: bool = False,
    ) -> Any:
        pass


@dataclass(frozen=True)
class _PreparedPackageAdjudication:
    payload: Any
    mode: str
    reason_codes: tuple[str, ...]


class DeepSeekPreparedGlossaryProvider:
    """DeepSeek-compatible glossary-prep provider adapter.

    The adapter returns only compact package payload plus metadata. Raw prompt
    and response bodies are recorded only by the existing provider IO capture
    boundary when that boundary is explicitly active.
    """

    def __init__(
        self,
        *,
        client: PreparedGlossaryChatClient,
        config: PreparedGlossaryDeepSeekProviderConfig | None = None,
    ) -> None:
        self._client = client
        self._config = config or PreparedGlossaryDeepSeekProviderConfig()

    def __call__(
        self,
        request: PreparedGlossaryProviderRequest,
    ) -> PreparedGlossaryProviderResponse:
        system_prompt = _system_prompt()
        user_prompt = _user_prompt(request.packet)
        try:
            result = self._client.create_chat_completion(
                system_prompt=system_prompt,
                user_text=user_prompt,
                response_format={"type": "json_object"},
                allow_empty_content=False,
            )
        except Exception as error:
            return PreparedGlossaryProviderResponse(
                payload=None,
                metadata=_metadata(
                    request,
                    status="failed",
                    reason_codes=("prepared_glossary_provider_call_failed",),
                    error_type=error.__class__.__name__,
                ),
            )

        usage = _usage_payload(getattr(result, "usage", None))
        payload, parse_reasons = _provider_package_payload(
            str(getattr(result, "content", "") or "")
        )
        adjudication = _adjudicate_provider_package_payload(
            payload,
            packet=request.packet,
            provider_model=self._config.provider_model,
        )
        reason_codes = (*parse_reasons, *adjudication.reason_codes)
        metadata = _metadata(
            request,
            status="ready" if isinstance(adjudication.payload, Mapping) else "failed",
            reason_codes=reason_codes,
            usage=usage,
            finish_reason=getattr(result, "finish_reason", None),
            adjudication=adjudication,
        )
        return PreparedGlossaryProviderResponse(
            payload=adjudication.payload
            if isinstance(adjudication.payload, Mapping)
            else None,
            metadata=metadata,
        )


def build_deepseek_prepared_glossary_provider(
    *,
    api_key: str,
    base_url: str,
    transport: Transport | None = None,
    timeout_seconds: float = 90.0,
    retry_attempts: int = 1,
    retry_delay_seconds: float = 0.0,
    config: PreparedGlossaryDeepSeekProviderConfig | None = None,
) -> DeepSeekPreparedGlossaryProvider:
    provider_config = config or PreparedGlossaryDeepSeekProviderConfig()
    client = DeepSeekClient(
        api_key=api_key,
        model=provider_config.provider_model,
        base_url=base_url,
        transport=transport,
        timeout_seconds=timeout_seconds,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )
    return DeepSeekPreparedGlossaryProvider(
        client=client,
        config=provider_config,
    )


def _system_prompt() -> str:
    return "\n".join(
        [
            "You are the DeepSeek Pro glossary preparation role.",
            "Return only one JSON object matching schema glossary-prepared-package-v1.",
            "Use only the candidates and evidence ids from the provided packet.",
            "Do not invent source entries, evidence ids, or raw passages.",
            (
                "Do not include raw source excerpts, prompt text, provider request/"
                "response bodies, translated passages, API keys or auth material."
            ),
            (
                "For every entry, provide target_canonical or target_variants for "
                "the requested target language, plus confidence, needs_review and "
                "metadata-only reason_codes."
            ),
        ]
    )


def _user_prompt(packet: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "task": "prepare_target_backed_glossary_package",
            "output_schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
            "required_provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
            "packet": packet,
            "output_requirements": {
                "owner_approved": True,
                "glossary_mode": "with_glossary",
                "source_language": packet.get("source_language", "Unknown"),
                "target_language": packet.get("target_language", "Unknown"),
                "provider_model": packet.get(
                    "provider_model",
                    DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
                ),
                "no_raw_excerpt_fields": True,
                "max_entries": packet.get("max_candidates", 8),
            },
            "output_package_skeleton": {
                "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
                "package_id": "use local envelope if unavailable",
                "source_language": packet.get("source_language", "Unknown"),
                "target_language": packet.get("target_language", "Unknown"),
                "glossary_mode": "with_glossary",
                "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
                "provider_model": packet.get(
                    "provider_model",
                    DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
                ),
                "provider_run_id": "metadata-only provider run id or Unknown",
                "source_document_fingerprint": packet.get(
                    "source_document_fingerprint",
                    "Unknown",
                ),
                "candidate_selector_signature": packet.get(
                    "candidate_selector_signature",
                    "Unknown",
                ),
                "owner_approved": True,
                "entries": [],
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _provider_package_payload(content: str) -> tuple[Any, tuple[str, ...]]:
    text = _strip_json_fence(content)
    try:
        return json.loads(text), ()
    except json.JSONDecodeError:
        return None, ("prepared_glossary_provider_response_invalid_json",)


def _adjudicate_provider_package_payload(
    payload: Any,
    *,
    packet: Mapping[str, Any],
    provider_model: str,
) -> _PreparedPackageAdjudication:
    payload, unwrap_reasons = _unwrap_provider_package_payload(payload)
    if not isinstance(payload, Mapping):
        return _PreparedPackageAdjudication(
            payload=None,
            mode="rejected",
            reason_codes=(*unwrap_reasons, "provider_package_not_object"),
        )
    unsafe_reasons = _unsafe_provider_payload_reasons(payload)
    if unsafe_reasons:
        return _PreparedPackageAdjudication(
            payload=None,
            mode="rejected",
            reason_codes=(*unwrap_reasons, *unsafe_reasons),
        )
    boundary_reasons = _top_level_boundary_reasons(
        payload,
        packet=packet,
        provider_model=provider_model,
    )
    if boundary_reasons:
        return _PreparedPackageAdjudication(
            payload=None,
            mode="rejected",
            reason_codes=(*unwrap_reasons, *boundary_reasons),
        )

    entries = payload.get("entries")
    if not isinstance(entries, Sequence) or isinstance(
        entries,
        (str, bytes, bytearray),
    ):
        return _PreparedPackageAdjudication(
            payload=None,
            mode="rejected",
            reason_codes=(*unwrap_reasons, "provider_package_entries_invalid"),
        )
    entries = list(entries)
    if not entries:
        return _PreparedPackageAdjudication(
            payload=None,
            mode="rejected",
            reason_codes=(*unwrap_reasons, "provider_package_entries_empty"),
        )
    max_candidates = _int_packet_value(packet, "max_candidates", default=8)
    if len(entries) > max_candidates:
        return _PreparedPackageAdjudication(
            payload=None,
            mode="rejected",
            reason_codes=(
                *unwrap_reasons,
                "provider_package_entry_count_exceeds_packet_bound",
            ),
        )
    entry_reasons = _entry_boundary_reasons(entries, packet=packet)
    if entry_reasons:
        return _PreparedPackageAdjudication(
            payload=None,
            mode="rejected",
            reason_codes=(*unwrap_reasons, *entry_reasons),
        )

    required_top_level = (
        "package_id",
        "owner_approved",
        "provider_role_id",
        "provider_model",
        "candidate_selector_signature",
    )
    envelope_reasons = _local_metadata_envelope_reasons(
        payload,
        packet=packet,
        provider_model=provider_model,
    )
    if all(key in payload for key in required_top_level) and not envelope_reasons:
        return _PreparedPackageAdjudication(
            payload=payload,
            mode="provider_package_as_is",
            reason_codes=unwrap_reasons,
        )

    source_document_fingerprint = str(
        packet.get("source_document_fingerprint") or "Unknown"
    )
    envelope = {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": _package_id(
            source_document_fingerprint,
            str(packet.get("target_language") or "Unknown"),
            len(entries),
        ),
        "source_language": str(packet.get("source_language") or "Unknown"),
        "target_language": str(packet.get("target_language") or "Unknown"),
        "glossary_mode": "with_glossary",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": provider_model,
        "provider_run_id": _provider_run_id(payload, packet=packet),
        "diagnostics_ref": "provider_io_diagnostics.jsonl",
        "source_document_fingerprint": source_document_fingerprint,
        "candidate_selector_signature": str(
            packet.get("candidate_selector_signature") or "Unknown"
        ),
        "owner_approved": True,
        "entries": _local_envelope_entries(entries, packet=packet),
    }
    return _PreparedPackageAdjudication(
        payload=envelope,
        mode="local_envelope_applied",
        reason_codes=(
            *unwrap_reasons,
            *envelope_reasons,
            "provider_package_missing_local_envelope_fields",
        ),
    )


def _unwrap_provider_package_payload(payload: Any) -> tuple[Any, tuple[str, ...]]:
    if not isinstance(payload, Mapping) or "output_package_skeleton" not in payload:
        return payload, ()
    if set(payload.keys()) != {"output_package_skeleton"}:
        return payload, ("provider_package_output_skeleton_wrapper_not_exclusive",)
    nested = payload.get("output_package_skeleton")
    if not isinstance(nested, Mapping):
        return payload, ("provider_package_output_skeleton_not_object",)
    return nested, ("provider_package_unwrapped_output_skeleton",)


def _top_level_boundary_reasons(
    payload: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    provider_model: str,
) -> tuple[str, ...]:
    allowed_keys = {
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
    reasons: list[str] = []
    if any(key not in allowed_keys for key in payload):
        reasons.append("provider_package_unsupported_top_level_field")
    source_language = payload.get("source_language")
    if (
        isinstance(source_language, str)
        and source_language.strip() != packet.get("source_language")
    ):
        reasons.append("provider_package_source_language_mismatch")
    target_language = payload.get("target_language")
    if (
        isinstance(target_language, str)
        and target_language.strip().lower()
        != str(packet.get("target_language") or "").lower()
    ):
        reasons.append("provider_package_target_language_mismatch")
    payload_model = payload.get("provider_model")
    if isinstance(payload_model, str) and payload_model.strip() != provider_model:
        reasons.append("provider_package_provider_model_mismatch")
    return _dedupe(reasons)


def _entry_boundary_reasons(
    entries: Sequence[Any],
    *,
    packet: Mapping[str, Any],
) -> tuple[str, ...]:
    packet_candidates = packet.get("candidates")
    if not isinstance(packet_candidates, Sequence) or isinstance(
        packet_candidates,
        (str, bytes, bytearray),
    ):
        return ("prep_packet_candidates_invalid",)
    allowed_entry_ids = {
        str(candidate.get("source_entry_id"))
        for candidate in packet_candidates
        if isinstance(candidate, Mapping) and candidate.get("source_entry_id")
    }
    allowed_evidence_ids = {
        str(evidence_id)
        for candidate in packet_candidates
        if isinstance(candidate, Mapping)
        for evidence_id in candidate.get("evidence_refs", ())
    }
    reasons: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            reasons.append("provider_package_entry_invalid")
            continue
        if str(entry.get("source_entry_id") or "") not in allowed_entry_ids:
            reasons.append("provider_package_source_entry_not_in_packet")
        evidence_refs = entry.get("evidence_refs", ())
        if not isinstance(evidence_refs, Sequence) or isinstance(
            evidence_refs,
            (str, bytes, bytearray),
        ):
            reasons.append("provider_package_evidence_refs_invalid")
            continue
        if any(
            str(evidence_id) not in allowed_evidence_ids
            for evidence_id in evidence_refs
        ):
            reasons.append("provider_package_evidence_ref_not_in_packet")
    return _dedupe(reasons)


def _local_metadata_envelope_reasons(
    payload: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    provider_model: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for field in {
        "package_id",
        "provider_run_id",
        "diagnostics_ref",
        "source_document_fingerprint",
        "candidate_selector_signature",
    }:
        if _is_placeholder_text(payload.get(field)):
            reasons.append("provider_package_local_metadata_placeholder")
            break
    if payload.get("owner_approved") is not True:
        reasons.append("provider_package_owner_approval_not_local_true")
    if payload.get("provider_role_id") != GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID:
        reasons.append("provider_package_provider_role_not_local_value")
    if payload.get("provider_model") != provider_model:
        reasons.append("provider_package_provider_model_not_local_value")
    if (
        isinstance(payload.get("source_document_fingerprint"), str)
        and payload.get("source_document_fingerprint")
        != packet.get("source_document_fingerprint")
    ):
        reasons.append("provider_package_source_fingerprint_not_local_value")
    if (
        isinstance(payload.get("candidate_selector_signature"), str)
        and payload.get("candidate_selector_signature")
        != packet.get("candidate_selector_signature")
    ):
        reasons.append("provider_package_selector_signature_not_local_value")
    return _dedupe(reasons)


def _local_envelope_entries(
    entries: Sequence[Any],
    *,
    packet: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates = packet.get("candidates", ())
    candidate_by_id = {
        str(candidate.get("source_entry_id")): candidate
        for candidate in candidates
        if isinstance(candidate, Mapping) and candidate.get("source_entry_id")
    }
    envelope_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        source_entry_id = str(entry.get("source_entry_id") or "")
        candidate = candidate_by_id.get(source_entry_id, {})
        envelope_entry = {
            "source_entry_id": source_entry_id,
            "source_canonical": str(candidate.get("source_canonical") or ""),
            "aliases": _safe_text_list(candidate.get("aliases", ()), limit=8),
            "evidence_refs": _safe_text_list(
                entry.get("evidence_refs") or candidate.get("evidence_refs", ()),
                limit=16,
            ),
            "source_unit_refs": _safe_int_list(
                candidate.get("source_unit_refs", ()),
                limit=16,
            ),
            "source_block_refs": _safe_text_list(
                candidate.get("source_block_refs", ()),
                limit=16,
            ),
            "target_canonical": entry.get("target_canonical"),
            "target_variants": entry.get("target_variants", ()),
            "forbidden_variants": entry.get("forbidden_variants", ()),
            "strategy": entry.get("strategy", "provider_prepared_local_envelope"),
            "confidence": entry.get("confidence", 0.0),
            "needs_review": entry.get("needs_review", False),
            "reason_codes": entry.get("reason_codes", entry.get("issue_codes", ())),
        }
        policy_metadata = entry.get("terminology_policy_metadata")
        if isinstance(policy_metadata, Mapping):
            envelope_entry["terminology_policy_metadata"] = dict(policy_metadata)
        envelope_entries.append(envelope_entry)
    return envelope_entries


def _unsafe_provider_payload_reasons(payload: Any) -> tuple[str, ...]:
    unsafe_keys = {
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
    secret_key_parts = (
        "api",
        "auth",
        "bearer",
        "dsn",
        "key",
        "password",
        "secret",
        "token",
    )
    secret_value_needles = ("sk-", "Bearer ", "Authorization:", "BEGIN PRIVATE KEY")
    unsafe_key_aliases = {
        "".join(ch for ch in unsafe_key if ch.isalnum())
        for unsafe_key in unsafe_keys
    }
    reasons: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = "".join(ch for ch in str(key).lower() if ch.isalnum())
                if normalized in unsafe_key_aliases:
                    reasons.append("provider_package_raw_field_rejected")
                if any(part in normalized for part in secret_key_parts):
                    reasons.append("provider_package_secret_field_rejected")
                visit(nested)
        elif isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            for item in value:
                visit(item)
        elif isinstance(value, str) and any(
            needle in value for needle in secret_value_needles
        ):
            reasons.append("provider_package_secret_value_rejected")

    visit(payload)
    return _dedupe(reasons)


def _metadata(
    request: PreparedGlossaryProviderRequest,
    *,
    status: str,
    reason_codes: Sequence[str],
    usage: Mapping[str, int] | None = None,
    finish_reason: str | None = None,
    adjudication: _PreparedPackageAdjudication | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    provider_model = str(
        request.packet.get(
            "provider_model",
            DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
        )
    ) or DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL
    metadata: dict[str, Any] = {
        "provider_status": status,
        "provider_model": provider_model,
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "reason_codes": list(_dedupe(reason_codes)),
    }
    if usage:
        metadata["provider_usage"] = dict(usage)
    if finish_reason is not None:
        metadata["finish_reason"] = str(finish_reason)
    if error_type is not None:
        metadata["error_type"] = str(error_type)
    if adjudication is not None:
        metadata["adjudication"] = {
            "mode": adjudication.mode,
            "reason_codes": list(adjudication.reason_codes),
        }
    return metadata


def _usage_payload(usage: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is None and isinstance(usage, Mapping):
            value = usage.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            result[key] = max(0, value)
    return result


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _provider_run_id(payload: Mapping[str, Any], *, packet: Mapping[str, Any]) -> str:
    value = payload.get("provider_run_id")
    if isinstance(value, str) and value.strip() and not _is_placeholder_text(value):
        return value.strip()[:180]
    fingerprint = str(packet.get("source_document_fingerprint") or "Unknown")
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"prepared-glossary-provider:{digest}"


def _package_id(
    source_document_fingerprint: str,
    target_language: str,
    entry_count: int,
) -> str:
    digest = hashlib.sha256(
        f"{source_document_fingerprint}:{target_language}:{entry_count}".encode()
    ).hexdigest()[:16]
    return f"prepared:runtime:{target_language}:{digest}"


def _int_packet_value(packet: Mapping[str, Any], key: str, *, default: int) -> int:
    value = packet.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(0, value)
    return default


def _safe_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if str(item)][:limit]


def _safe_int_list(value: Any, *, limit: int) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int) and item >= 0:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def _is_placeholder_text(value: Any) -> bool:
    if not isinstance(value, str):
        return value is None
    normalized = value.strip().lower()
    if not normalized:
        return True
    return any(
        needle in normalized
        for needle in (
            "unknown",
            "unavailable",
            "use package_id",
            "local envelope",
            "local wrapper",
            "if unavailable",
        )
    )


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)
