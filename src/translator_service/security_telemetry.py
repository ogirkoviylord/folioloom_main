from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
import logging
from collections.abc import Mapping
from typing import Any, Callable
import re


logger = logging.getLogger(__name__)


_SAFE_PAYLOAD_KEYS = {
    "attempt",
    "blocked_security_event_type",
    "cooldown_remaining_seconds",
    "cooldown_seconds",
    "count",
    "completed_units",
    "document_format",
    "error_type",
    "expected_count",
    "exit_code",
    "fragment_sequence",
    "job_id",
    "limit_cpu_seconds",
    "limit_file_size_mb",
    "limit_memory_mb",
    "limit_open_files",
    "limit_process_count",
    "limit_timeout_seconds",
    "limit",
    "max_request_bytes",
    "max_result_bytes",
    "max_stderr_bytes",
    "max_stdout_bytes",
    "operation",
    "output_chars",
    "phase",
    "reason",
    "request_bytes",
    "result_bytes",
    "retry_attempt",
    "security_event_type",
    "source_chars",
    "status",
    "stderr_bytes",
    "stdout_bytes",
    "timeout_seconds",
    "total_units",
    "threshold_count",
    "window_seconds",
    "work_unit_id",
}


@dataclass(frozen=True)
class SecurityThresholdPolicy:
    max_events_per_run: int = 20
    max_unsafe_model_outputs_per_run: int = 3
    max_repair_failures_per_run: int = 1
    max_translation_batch_rejections_per_run: int = 6
    enabled: bool = True


class SecurityThresholdExceeded(RuntimeError):
    def __init__(
        self,
        *,
        event_type: str,
        count: int,
        limit: int,
        reason: str | None = None,
    ) -> None:
        self.event_type = event_type
        self.count = count
        self.limit = limit
        self.reason = reason
        message = (
            "Security threshold exceeded: "
            f"event_type={event_type} count={count} limit={limit}"
        )
        if reason:
            message = f"{message} reason={reason}"
        super().__init__(message)


class SecurityEventLimiter:
    def __init__(self, policy: SecurityThresholdPolicy | None = None) -> None:
        self._policy = policy or SecurityThresholdPolicy()
        self._event_counts: dict[str, int] = {}
        self._total_events = 0

    def observe(self, event: object) -> None:
        normalized = normalize_security_event(event)
        if normalized is None or not self._policy.enabled:
            return

        event_type = normalized["event_type"]
        reason = normalized["payload"].get("reason")
        self._total_events += 1
        self._raise_if_over_limit(
            event_type="security_event",
            count=self._total_events,
            limit=self._policy.max_events_per_run,
            reason=str(reason) if reason else None,
        )

        self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1
        event_limit = self._event_limit(event_type)
        if event_limit is not None:
            self._raise_if_over_limit(
                event_type=event_type,
                count=self._event_counts[event_type],
                limit=event_limit,
                reason=str(reason) if reason else None,
            )

    def _event_limit(self, event_type: str) -> int | None:
        if event_type == "unsafe_model_output":
            return self._policy.max_unsafe_model_outputs_per_run
        if event_type == "model_output_repair_failed":
            return self._policy.max_repair_failures_per_run
        if event_type == "translation_batch_rejected":
            return self._policy.max_translation_batch_rejections_per_run
        return None

    @staticmethod
    def _raise_if_over_limit(
        *,
        event_type: str,
        count: int,
        limit: int,
        reason: str | None,
    ) -> None:
        if limit > 0 and count > limit:
            raise SecurityThresholdExceeded(
                event_type=event_type,
                count=count,
                limit=limit,
                reason=reason,
            )


@dataclass(frozen=True)
class SecurityCooldownPolicy:
    max_thresholds_per_window: int = 2
    window_seconds: int = 3600
    cooldown_seconds: int = 900
    enabled: bool = True


class SecurityCooldownActive(RuntimeError):
    def __init__(
        self,
        *,
        user_id: str,
        cooldown_until: float,
        now: float,
    ) -> None:
        self.user_id = user_id
        self.cooldown_until = cooldown_until
        self.remaining_seconds = max(0, int(round(cooldown_until - now)))
        super().__init__(
            "Security cooldown active: "
            f"user_id={user_id} remaining_seconds={self.remaining_seconds}"
        )


class SecurityCooldownTracker:
    def __init__(
        self,
        policy: SecurityCooldownPolicy | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._policy = policy or SecurityCooldownPolicy()
        self._clock = clock or _default_clock
        self._incidents: dict[str, list[float]] = {}
        self._cooldown_until: dict[str, float] = {}

    def assert_allowed(self, user_id: str) -> None:
        if not self._policy.enabled:
            return
        now = self._clock()
        cooldown_until = self._cooldown_until.get(user_id)
        if cooldown_until is None:
            return
        if now < cooldown_until:
            raise SecurityCooldownActive(
                user_id=user_id,
                cooldown_until=cooldown_until,
                now=now,
            )
        self._cooldown_until.pop(user_id, None)

    def record_threshold_exceeded(self, user_id: str) -> SecurityCooldownActive | None:
        if (
            not self._policy.enabled
            or self._policy.max_thresholds_per_window <= 0
            or self._policy.cooldown_seconds <= 0
        ):
            return None

        now = self._clock()
        self._prune_user(user_id, now=now)
        incidents = self._incidents.setdefault(user_id, [])
        incidents.append(now)
        if len(incidents) < self._policy.max_thresholds_per_window:
            return None

        cooldown_until = now + self._policy.cooldown_seconds
        self._cooldown_until[user_id] = cooldown_until
        return SecurityCooldownActive(
            user_id=user_id,
            cooldown_until=cooldown_until,
            now=now,
        )

    def _prune_user(self, user_id: str, *, now: float) -> None:
        window_started_at = now - max(0, self._policy.window_seconds)
        self._incidents[user_id] = [
            incident_at
            for incident_at in self._incidents.get(user_id, [])
            if incident_at >= window_started_at
        ]


def build_security_event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {
        "event_type": _safe_label(event_type),
        "payload": sanitize_security_payload(payload),
    }


def record_security_event(event_type: str, **payload: Any) -> dict[str, Any]:
    event = build_security_event(event_type, **payload)
    logger.warning(
        "security_event %s",
        json.dumps(event, ensure_ascii=False, sort_keys=True),
    )
    return event


def normalize_security_event(event: object) -> dict[str, Any] | None:
    if event is None:
        return None
    if is_dataclass(event) and not isinstance(event, type):
        event = asdict(event)
    elif not isinstance(event, Mapping):
        event_type = getattr(event, "event_type", None)
        if event_type is None:
            event_type = getattr(event, "type", None)
        event = {
            "event_type": event_type,
            "payload": getattr(event, "payload", {}),
        }

    if not isinstance(event, Mapping):
        return None

    event_type = event.get("event_type") or event.get("type")
    if not isinstance(event_type, str) or not event_type:
        return None

    raw_payload = event.get("payload")
    if isinstance(raw_payload, Mapping):
        payload = dict(raw_payload)
    else:
        payload = {
            str(key): value
            for key, value in event.items()
            if key not in {"event_type", "type", "payload"}
        }
    return build_security_event(event_type, **payload)


def sanitize_security_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in _SAFE_PAYLOAD_KEYS:
            continue
        safe_value = _safe_scalar(value)
        if safe_value is not _UNSAFE_VALUE:
            sanitized[key] = safe_value
    return sanitized


_UNSAFE_VALUE = object()


def _safe_scalar(value: Any) -> str | int | float | bool | None | object:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:256]
    return _UNSAFE_VALUE


def _safe_label(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", value.strip()).strip("_").lower()
    return normalized[:80] or "unknown"


def _default_clock() -> float:
    import time

    return time.time()
