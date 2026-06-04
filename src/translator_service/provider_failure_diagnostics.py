from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProviderFailureCategory(StrEnum):
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE_5XX = "unavailable_5xx"
    AUTH = "auth"
    BILLING = "billing"
    MALFORMED_RESPONSE = "malformed_response"
    UNSAFE_MODEL_OUTPUT = "unsafe_model_output"
    NETWORK = "network"
    CIRCUIT_OPEN = "circuit_open"
    PROVIDER_OTHER = "provider_other"


@dataclass(frozen=True)
class ProviderFailureClassification:
    failure_category: ProviderFailureCategory
    http_status_bucket: str | None = None


@dataclass(frozen=True)
class ProviderFailureDiagnostic:
    failure_category: ProviderFailureCategory
    http_status_bucket: str | None = None
    provider_id: str = "deepseek"
    channel_fingerprint: str | None = None
    channel_health: str | None = None
    channel_error_kind: str | None = None
    latency_ms: float | None = None
    retry_after_seconds: int | None = None
    terminal_reason: str | None = None
    adaptive_circuit_snapshot: dict[str, object] | None = None

    def to_safe_payload(
        self,
        *,
        retry_after_seconds: int | None = None,
        terminal_reason: str | None = None,
        attempt_number: int | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "failure_category": self.failure_category.value,
            "provider_id": self.provider_id,
        }
        if attempt_number is not None:
            payload["attempt_number"] = max(0, int(attempt_number))
        if self.http_status_bucket:
            payload["http_status_bucket"] = self.http_status_bucket
        retry_after = (
            retry_after_seconds
            if retry_after_seconds is not None
            else self.retry_after_seconds
        )
        if retry_after is not None:
            payload["retry_after_seconds"] = max(0, int(retry_after))
        terminal = terminal_reason if terminal_reason is not None else self.terminal_reason
        if terminal is not None:
            payload["terminal_reason"] = terminal
        if self.latency_ms is not None:
            payload["latency_ms"] = round(max(0.0, float(self.latency_ms)), 3)
        channel = _safe_channel_payload(
            channel_fingerprint=self.channel_fingerprint,
            channel_health=self.channel_health,
            channel_error_kind=self.channel_error_kind,
        )
        if channel:
            payload["channel"] = channel
        if self.adaptive_circuit_snapshot:
            payload["adaptive_circuit"] = dict(self.adaptive_circuit_snapshot)
        return payload


def classify_provider_failure(error: BaseException) -> ProviderFailureClassification:
    message = str(error)
    lowered = message.lower()
    status = _http_status(message)
    bucket = _http_status_bucket(status)
    class_name = error.__class__.__name__.lower()

    if "unsafe_model_output" in lowered or "unsafe model output" in lowered:
        return ProviderFailureClassification(
            ProviderFailureCategory.UNSAFE_MODEL_OUTPUT,
            bucket,
        )
    if "deepseekunsafemodeloutputerror" in class_name:
        return ProviderFailureClassification(
            ProviderFailureCategory.UNSAFE_MODEL_OUTPUT,
            bucket,
        )
    if status == 429 or "rate limit" in lowered or "rate-limited" in lowered:
        return ProviderFailureClassification(ProviderFailureCategory.RATE_LIMITED, "429")
    if "circuit open" in lowered or "no available channels" in lowered:
        return ProviderFailureClassification(ProviderFailureCategory.CIRCUIT_OPEN, bucket)
    if "timeout" in lowered or "timed out" in lowered:
        return ProviderFailureClassification(ProviderFailureCategory.TIMEOUT, bucket)
    if status is not None and 500 <= status <= 599:
        return ProviderFailureClassification(
            ProviderFailureCategory.UNAVAILABLE_5XX,
            "5xx",
        )
    if "unavailable" in lowered:
        return ProviderFailureClassification(
            ProviderFailureCategory.UNAVAILABLE_5XX,
            bucket,
        )
    if status in {401, 403} or "auth" in lowered:
        return ProviderFailureClassification(ProviderFailureCategory.AUTH, bucket)
    if "billing" in lowered or "insufficient" in lowered or "quota" in lowered:
        return ProviderFailureClassification(ProviderFailureCategory.BILLING, bucket)
    if any(
        marker in lowered
        for marker in (
            "malformed",
            "invalid json",
            "not valid json",
            "invalid translation batch",
            "did not contain message content",
            "message content is empty",
            "response json was not",
        )
    ):
        return ProviderFailureClassification(
            ProviderFailureCategory.MALFORMED_RESPONSE,
            bucket,
        )
    if any(
        marker in lowered
        for marker in (
            "network",
            "connection",
            "urlerror",
            "ssl",
            "request failed",
        )
    ):
        return ProviderFailureClassification(ProviderFailureCategory.NETWORK, bucket)
    return ProviderFailureClassification(ProviderFailureCategory.PROVIDER_OTHER, bucket)


def build_provider_failure_diagnostic(
    error: BaseException,
    *,
    translator: object | None = None,
    provider_id: str = "deepseek",
) -> ProviderFailureDiagnostic:
    classification = classify_provider_failure(error)
    channel = _select_channel_snapshot(
        _call_tuple_method(translator, "snapshot"),
        classification.failure_category,
    )
    adaptive = _safe_adaptive_snapshot(_call_method(translator, "provider_snapshot"))
    return ProviderFailureDiagnostic(
        failure_category=classification.failure_category,
        http_status_bucket=classification.http_status_bucket,
        provider_id=provider_id,
        channel_fingerprint=_channel_fingerprint(channel, provider_id=provider_id),
        channel_health=_string_attr(channel, "health"),
        channel_error_kind=_mapped_channel_error_kind(_string_attr(channel, "error_kind")),
        latency_ms=_float_attr(channel, "last_latency_ms"),
        adaptive_circuit_snapshot=adaptive,
    )


def provider_diagnostic_is_actionable(
    diagnostic: ProviderFailureDiagnostic,
    error: BaseException,
) -> bool:
    if diagnostic.failure_category is not ProviderFailureCategory.PROVIDER_OTHER:
        return True
    message = str(error).lower()
    return bool(diagnostic.http_status_bucket) or "deepseek" in message


def _http_status(message: str) -> int | None:
    match = re.search(r"\bhttp\s+(\d{3})\b", message, flags=re.IGNORECASE)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _http_status_bucket(status: int | None) -> str | None:
    if status is None:
        return None
    if status == 429:
        return "429"
    if 500 <= status <= 599:
        return "5xx"
    if 400 <= status <= 499:
        return "4xx"
    return str(status)


def _call_method(value: object | None, name: str) -> object | None:
    method = getattr(value, name, None)
    if method is None or not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def _call_tuple_method(value: object | None, name: str) -> tuple[object, ...]:
    result = _call_method(value, name)
    if isinstance(result, tuple):
        return result
    if isinstance(result, list):
        return tuple(result)
    return ()


def _select_channel_snapshot(
    channels: tuple[object, ...],
    category: ProviderFailureCategory,
) -> object | None:
    if not channels:
        return None
    expected = _channel_error_kind_for_category(category)
    matching = [
        channel
        for channel in channels
        if _mapped_channel_error_kind(_string_attr(channel, "error_kind")) == expected
    ]
    candidates = matching or [
        channel for channel in channels if _string_attr(channel, "error_kind")
    ]
    if not candidates:
        return channels[0]
    return max(
        candidates,
        key=lambda channel: (
            _float_attr(channel, "last_failure_at") is not None,
            _float_attr(channel, "last_failure_at") or 0.0,
            _float_attr(channel, "last_latency_ms") or 0.0,
        ),
    )


def _channel_error_kind_for_category(category: ProviderFailureCategory) -> str:
    if category is ProviderFailureCategory.UNAVAILABLE_5XX:
        return "unavailable_5xx"
    if category is ProviderFailureCategory.PROVIDER_OTHER:
        return "provider_other"
    return category.value


def _mapped_channel_error_kind(value: str | None) -> str | None:
    if value == "unavailable":
        return "unavailable_5xx"
    if value == "provider_error":
        return "provider_other"
    return value


def _channel_fingerprint(channel: object | None, *, provider_id: str) -> str | None:
    label = _string_attr(channel, "label")
    if not label:
        return None
    digest = hashlib.sha256(f"{provider_id}:{label}".encode("utf-8")).hexdigest()
    return f"chan_{digest[:12]}"


def _safe_adaptive_snapshot(snapshot: object | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    keys = (
        "enabled",
        "current_limit",
        "max_capacity",
        "active_requests",
        "available_slots",
        "circuit_state",
        "circuit_open_remaining_seconds",
        "last_reason",
        "total_decreases",
        "total_circuit_opened",
    )
    payload: dict[str, object] = {}
    for key in keys:
        value = getattr(snapshot, key, None)
        if value is not None:
            payload[key] = _safe_scalar(value)
    return payload or None


def _safe_channel_payload(
    *,
    channel_fingerprint: str | None,
    channel_health: str | None,
    channel_error_kind: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if channel_fingerprint:
        payload["channel_fingerprint"] = channel_fingerprint
    if channel_health:
        payload["health"] = channel_health
    if channel_error_kind:
        payload["error_kind"] = channel_error_kind
    return payload


def _string_attr(value: object | None, name: str) -> str | None:
    item = getattr(value, name, None)
    if item is None:
        return None
    text = str(item).strip()
    return text or None


def _float_attr(value: object | None, name: str) -> float | None:
    item = getattr(value, name, None)
    if item is None:
        return None
    try:
        return float(item)
    except (TypeError, ValueError):
        return None


def _safe_scalar(value: Any) -> object:
    if isinstance(value, bool | int | float | str):
        return value
    return str(value)
