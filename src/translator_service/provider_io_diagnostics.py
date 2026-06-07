from __future__ import annotations

import base64
import hashlib
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

ProviderIODiagnosticSink = Callable[[dict[str, object]], None]


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
        "url": url,
        "transport_attempt": transport_attempt,
        "request_body": _bytes_payload(request_body),
        "response_body": (
            _bytes_payload(response_body) if response_body is not None else None
        ),
        "http_status": http_status,
        "error": _safe_error_payload(error) if error is not None else None,
    }
    sink(record)


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


def _safe_error_payload(error: BaseException) -> dict[str, object]:
    return {
        "type": error.__class__.__name__,
        "message": str(error),
    }
