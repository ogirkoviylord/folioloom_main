from __future__ import annotations

import base64
import hashlib
import logging
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

ProviderIODiagnosticSink = Callable[[dict[str, object]], None]
logger = logging.getLogger(__name__)

_AUTH_MATERIAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"Authorization\s*:\s*Bearer\s+[^\s,;\"']+", re.IGNORECASE),
        "Authorization: [redacted]",
    ),
    (re.compile(r"\bBearer\s+[^\s,;\"']+", re.IGNORECASE), "Bearer [redacted]"),
    (re.compile(r"\bsk-[A-Za-z0-9._-]{3,}\b"), "[redacted-api-key]"),
    (
        re.compile(r"\b(api[_-]?key=)[^\s&;,\"']+", re.IGNORECASE),
        r"\1[redacted]",
    ),
    (
        re.compile(r"\b(secret[_-]?id=)[^\s&;,\"']+", re.IGNORECASE),
        r"\1[redacted]",
    ),
    (
        re.compile(r"\b[A-Za-z0-9_.-]*api_keys[A-Za-z0-9_.-]*\b", re.IGNORECASE),
        "[redacted-secret-id]",
    ),
)


@dataclass(frozen=True)
class ProviderIODiagnosticContext:
    job_id: str
    work_unit_id: str | None = None
    sequence: int | None = None


_state = threading.local()


@contextmanager
def capture_provider_io(
    sink: ProviderIODiagnosticSink | None,
    *,
    job_id: str,
    work_unit_id: str | None = None,
    sequence: int | None = None,
) -> Iterator[None]:
    if sink is None or not job_id:
        yield
        return

    previous = getattr(_state, "capture", None)
    _state.capture = (
        sink,
        ProviderIODiagnosticContext(
            job_id=job_id,
            work_unit_id=work_unit_id,
            sequence=sequence,
        ),
    )
    try:
        yield
    finally:
        if previous is None:
            try:
                delattr(_state, "capture")
            except AttributeError:
                pass
        else:
            _state.capture = previous


def record_provider_io_exchange(
    *,
    provider_id: str,
    url: str,
    request_body: bytes,
    http_status: int | None = None,
    response_body: bytes | None = None,
    transport_attempt: int | None = None,
    error: BaseException | None = None,
) -> None:
    capture = getattr(_state, "capture", None)
    if capture is None:
        return

    sink, context = capture
    record: dict[str, object] = {
        "schema_version": "provider-io-diagnostics-v1",
        "diagnostic_scope": "owner_only_translation_run_archive",
        "timestamp": datetime.now(UTC).isoformat(),
        "provider_id": provider_id,
        "job_id": context.job_id,
        "work_unit_id": context.work_unit_id,
        "sequence": context.sequence,
        "url": redact_provider_auth_material(url),
        "transport_attempt": transport_attempt,
        "request_body": _bytes_payload(request_body),
        "response_body": (
            _bytes_payload(response_body) if response_body is not None else None
        ),
        "http_status": http_status,
        "error": _safe_error_payload(error) if error is not None else None,
    }
    try:
        sink(record)
    except Exception as error:
        logger.warning(
            "Provider IO diagnostic sink failed: provider_id=%s job_id=%s "
            "work_unit_id=%s error_type=%s",
            provider_id,
            context.job_id,
            context.work_unit_id,
            error.__class__.__name__,
        )


def _bytes_payload(value: bytes) -> dict[str, object]:
    payload: dict[str, object] = {
        "sha256": hashlib.sha256(value).hexdigest(),
        "byte_count": len(value),
    }
    try:
        payload["text"] = value.decode("utf-8")
    except UnicodeDecodeError:
        payload["base64"] = base64.b64encode(value).decode("ascii")
        payload["encoding"] = "base64"
    else:
        payload["encoding"] = "utf-8"
    return payload


def redact_provider_auth_material(value: str) -> str:
    redacted = value
    for pattern, replacement in _AUTH_MATERIAL_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _safe_error_payload(error: BaseException) -> dict[str, object]:
    return {
        "type": error.__class__.__name__,
        "message": redact_provider_auth_material(str(error)),
    }
