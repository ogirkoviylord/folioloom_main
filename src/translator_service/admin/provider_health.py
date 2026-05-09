from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from translator_service.admin.ai_provider_keys import AIProviderKeySummary
from translator_service.admin.integrations import IntegrationSummary

_DEFAULT_VALIDATION_STATUS = "not checked"
_DEFAULT_ERROR_EXCERPT = "n/a"
_MAX_ERROR_EXCERPT_LENGTH = 120
_DEGRADED_VALIDATION_STATUSES = {"cooldown", "error", "failed", "failure"}
_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|secret_id|value)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9._-]+"),
    re.compile(r"\b[A-Za-z0-9._-]*api_keys[A-Za-z0-9._-]*\b"),
)


@dataclass(frozen=True)
class ProviderHealthSummary:
    provider_id: str
    label: str
    active_key_count: int
    disabled_key_count: int
    total_key_count: int
    status: str
    last_validation_status: str
    last_error_excerpt: str
    can_test: bool


ValidationMetadata = Mapping[str, Mapping[str, Any]]


def build_provider_health(
    summaries: tuple[IntegrationSummary, ...],
    key_pools: Mapping[str, tuple[AIProviderKeySummary, ...]],
    validation_metadata: ValidationMetadata | None = None,
) -> tuple[ProviderHealthSummary, ...]:
    metadata = validation_metadata or {}
    return tuple(
        _provider_health_summary(
            summary,
            keys=key_pools.get(summary.integration_id, ()),
            metadata=metadata.get(summary.integration_id, {}),
        )
        for summary in summaries
    )


def _provider_health_summary(
    summary: IntegrationSummary,
    *,
    keys: tuple[AIProviderKeySummary, ...],
    metadata: Mapping[str, Any],
) -> ProviderHealthSummary:
    active_key_count = sum(1 for key in keys if key.enabled and not key.disabled)
    total_key_count = len(keys)
    disabled_key_count = total_key_count - active_key_count
    last_validation_status = _metadata_text(
        metadata,
        "last_validation_status",
        default=_DEFAULT_VALIDATION_STATUS,
    )
    last_error_excerpt = _last_error_excerpt(metadata)
    status = _provider_status(
        active_key_count=active_key_count,
        last_validation_status=last_validation_status,
        last_error_excerpt=last_error_excerpt,
    )
    return ProviderHealthSummary(
        provider_id=summary.integration_id,
        label=summary.label,
        active_key_count=active_key_count,
        disabled_key_count=disabled_key_count,
        total_key_count=total_key_count,
        status=status,
        last_validation_status=last_validation_status,
        last_error_excerpt=last_error_excerpt,
        can_test=active_key_count > 0,
    )


def _provider_status(
    *,
    active_key_count: int,
    last_validation_status: str,
    last_error_excerpt: str,
) -> str:
    if active_key_count == 0:
        return "missing_keys"
    if (
        last_validation_status.lower() in _DEGRADED_VALIDATION_STATUSES
        or last_error_excerpt != _DEFAULT_ERROR_EXCERPT
    ):
        return "degraded"
    return "healthy"


def _last_error_excerpt(metadata: Mapping[str, Any]) -> str:
    value = metadata.get("last_error_excerpt", metadata.get("last_error"))
    if value is None:
        return _DEFAULT_ERROR_EXCERPT
    excerpt = _redact_sensitive_text(str(value))
    if not excerpt:
        return _DEFAULT_ERROR_EXCERPT
    if len(excerpt) > _MAX_ERROR_EXCERPT_LENGTH:
        return excerpt[: _MAX_ERROR_EXCERPT_LENGTH - 3].rstrip() + "..."
    return excerpt


def _metadata_text(
    metadata: Mapping[str, Any],
    key: str,
    *,
    default: str,
) -> str:
    value = metadata.get(key)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _redact_sensitive_text(value: str) -> str:
    redacted = " ".join(value.split())
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted
