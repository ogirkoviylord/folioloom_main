from __future__ import annotations

import base64
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from translator_service.documents import DocumentFormat
from translator_service.extractors import TextExtractionError
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.security_telemetry import record_security_event
from translator_service.structure_optimizer import PromptTier, TextBlockKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentSandboxLimits:
    timeout_seconds: float = 10.0
    cpu_seconds: int = 5
    memory_mb: int = 512
    file_size_mb: int = 128
    process_count: int = 16
    open_files: int = 64
    max_request_bytes: int = 96 * 1024 * 1024
    max_stdout_bytes: int = 192 * 1024 * 1024
    max_stderr_bytes: int = 1024 * 1024
    max_result_bytes: int = 192 * 1024 * 1024


@dataclass(frozen=True)
class SandboxTranslationUnit:
    source_block_ids: tuple[str, ...]
    translated_text: str


class DocumentSandboxError(TextExtractionError):
    pass


class DocumentSandboxTimeout(DocumentSandboxError):
    pass


class DocumentSandbox:
    def __init__(
        self,
        *,
        limits: DocumentSandboxLimits | None = None,
        python_executable: str | None = None,
        worker_module: str = "translator_service.document_sandbox_worker",
    ) -> None:
        self._limits = limits or DocumentSandboxLimits()
        self._python_executable = python_executable or sys.executable
        self._worker_module = worker_module

    def extract_text(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
    ) -> str:
        result = self._request(
            {
                "operation": "extract_text",
                "document_format": document_format.value,
                "content_b64": _encode_content(content),
            }
        )
        text = result.get("text")
        if not isinstance(text, str):
            raise DocumentSandboxError("Document sandbox returned invalid text result")
        return text

    def plan_translation(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
        max_fragment_chars: int,
        translation_mode: str | None = None,
    ) -> FormatAdapterPlan:
        request = {
            "operation": "plan_translation",
            "document_format": document_format.value,
            "content_b64": _encode_content(content),
            "max_fragment_chars": max_fragment_chars,
        }
        if translation_mode is not None:
            request["translation_mode"] = translation_mode
        result = self._request(request)
        return _adapter_plan_from_json(result)

    def assemble_document(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
        translated_units: Sequence[SandboxTranslationUnit],
    ) -> bytes:
        result = self._request(
            {
                "operation": "assemble_document",
                "document_format": document_format.value,
                "content_b64": _encode_content(content),
                "translated_units": [
                    _sandbox_translation_unit_to_json(unit)
                    for unit in translated_units
                ],
            }
        )
        content_b64 = result.get("content_b64")
        if not isinstance(content_b64, str):
            raise DocumentSandboxError(
                "Document sandbox returned invalid assembled content"
            )
        try:
            return base64.b64decode(content_b64, validate=True)
        except ValueError as error:
            raise DocumentSandboxError(
                "Document sandbox returned invalid assembled content"
            ) from error

    def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
        event_context = _security_event_context(request, self._limits)
        if len(payload) > self._limits.max_request_bytes:
            record_security_event(
                "document_sandbox_request_too_large",
                request_bytes=len(payload),
                **event_context,
            )
            raise DocumentSandboxError("Document sandbox request is too large")

        command = [self._python_executable, "-m", self._worker_module]
        try:
            with tempfile.TemporaryDirectory(
                prefix="translator-document-sandbox-",
            ) as temp_dir:
                completed = subprocess.run(
                    command,
                    input=payload,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self._limits.timeout_seconds,
                    env=_sandbox_environment(
                        os.environ,
                        temp_dir=temp_dir,
                        limits=self._limits,
                    ),
                    cwd=temp_dir,
                    close_fds=True,
                    start_new_session=os.name == "posix",
                    preexec_fn=_resource_limiter(self._limits),
                )
        except subprocess.TimeoutExpired as error:
            record_security_event("document_sandbox_timeout", **event_context)
            raise DocumentSandboxTimeout("Document sandbox timed out") from error

        if len(completed.stdout) > self._limits.max_stdout_bytes:
            record_security_event(
                "document_sandbox_output_too_large",
                stdout_bytes=len(completed.stdout),
                **event_context,
            )
            raise DocumentSandboxError("Document sandbox output is too large")

        if len(completed.stderr) > self._limits.max_stderr_bytes:
            record_security_event(
                "document_sandbox_stderr_too_large",
                stderr_bytes=len(completed.stderr),
                **event_context,
            )
            raise DocumentSandboxError("Document sandbox stderr is too large")

        if completed.returncode != 0:
            record_security_event(
                "document_sandbox_failure",
                exit_code=completed.returncode,
                **event_context,
            )
            raise DocumentSandboxError(
                f"Document sandbox process failed with exit code {completed.returncode}"
            )

        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            record_security_event(
                "document_sandbox_invalid_response",
                stdout_bytes=len(completed.stdout),
                **event_context,
            )
            raise DocumentSandboxError("Document sandbox returned invalid JSON") from error

        if not isinstance(response, dict):
            record_security_event("document_sandbox_invalid_response", **event_context)
            raise DocumentSandboxError("Document sandbox returned invalid response")

        if not response.get("ok"):
            message = response.get("message")
            record_security_event(
                "document_sandbox_failure",
                error_type=str(response.get("error_type") or "worker_error"),
                **event_context,
            )
            raise DocumentSandboxError(
                str(message) if message else "Document sandbox failed"
            )

        result = response.get("result")
        if not isinstance(result, dict):
            record_security_event("document_sandbox_invalid_response", **event_context)
            raise DocumentSandboxError("Document sandbox returned invalid result")
        result_bytes = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        if result_bytes > self._limits.max_result_bytes:
            record_security_event(
                "document_sandbox_output_too_large",
                result_bytes=result_bytes,
                **event_context,
            )
            raise DocumentSandboxError("Document sandbox result is too large")
        return result


def _sandbox_environment(
    source: os._Environ[str] | dict[str, str],
    *,
    temp_dir: str | None = None,
    limits: DocumentSandboxLimits | None = None,
) -> dict[str, str]:
    env: dict[str, str] = {
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "DOCUMENT_SANDBOX_DISABLE_NETWORK": "1",
    }
    if limits is not None:
        env["DOCUMENT_SANDBOX_MAX_STDIN_BYTES"] = str(limits.max_request_bytes)
    if temp_dir is not None:
        env["HOME"] = temp_dir
        env["TMPDIR"] = temp_dir
        env["TMP"] = temp_dir
        env["TEMP"] = temp_dir
    for name in ("PYTHONPATH", "PYTHONPYCACHEPREFIX", "SYSTEMROOT"):
        value = source.get(name)
        if value:
            env[name] = _absolute_pythonpath(value) if name == "PYTHONPATH" else value
    return env


def _absolute_pythonpath(value: str) -> str:
    parts = []
    for item in value.split(os.pathsep):
        if not item:
            continue
        parts.append(item if os.path.isabs(item) else os.path.abspath(item))
    return os.pathsep.join(parts)


def _resource_limiter(limits: DocumentSandboxLimits):
    if os.name != "posix":
        return None

    def limit_resources() -> None:
        import resource

        cpu_seconds = max(1, int(math.ceil(limits.cpu_seconds)))
        _set_resource_limit(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1)
        if limits.file_size_mb > 0:
            file_bytes = limits.file_size_mb * 1024 * 1024
            _set_resource_limit(resource.RLIMIT_FSIZE, file_bytes, file_bytes)
        if limits.memory_mb > 0 and hasattr(resource, "RLIMIT_AS"):
            memory_bytes = limits.memory_mb * 1024 * 1024
            _set_resource_limit(resource.RLIMIT_AS, memory_bytes, memory_bytes)
        if limits.process_count > 0 and hasattr(resource, "RLIMIT_NPROC"):
            _set_resource_limit(
                resource.RLIMIT_NPROC,
                limits.process_count,
                limits.process_count,
            )
        if limits.open_files > 0 and hasattr(resource, "RLIMIT_NOFILE"):
            _set_resource_limit(
                resource.RLIMIT_NOFILE,
                limits.open_files,
                limits.open_files,
            )
        try:
            os.umask(0o077)
        except OSError:
            logger.warning("Failed to set umask in sandbox", exc_info=True)
            return

    return limit_resources


def _set_resource_limit(resource_name: int, soft: int, hard: int) -> None:
    try:
        import resource

        resource.setrlimit(resource_name, (soft, hard))
    except (OSError, ValueError):
        logger.warning("Failed to set resource limit %s", resource_name, exc_info=True)
        return


def _encode_content(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _security_event_context(
    request: dict[str, Any],
    limits: DocumentSandboxLimits,
) -> dict[str, Any]:
    return {
        "operation": str(request.get("operation") or "unknown"),
        "document_format": str(request.get("document_format") or "unknown"),
        "limit_timeout_seconds": limits.timeout_seconds,
        "limit_cpu_seconds": limits.cpu_seconds,
        "limit_memory_mb": limits.memory_mb,
        "limit_file_size_mb": limits.file_size_mb,
        "limit_process_count": limits.process_count,
        "limit_open_files": limits.open_files,
        "max_request_bytes": limits.max_request_bytes,
        "max_stdout_bytes": limits.max_stdout_bytes,
        "max_stderr_bytes": limits.max_stderr_bytes,
        "max_result_bytes": limits.max_result_bytes,
    }


def _sandbox_translation_unit_to_json(
    unit: SandboxTranslationUnit,
) -> dict[str, Any]:
    return {
        "source_block_ids": list(unit.source_block_ids),
        "translated_text": unit.translated_text,
    }


def _adapter_plan_from_json(payload: dict[str, Any]) -> FormatAdapterPlan:
    units_payload = payload.get("units")
    if not isinstance(units_payload, list):
        raise DocumentSandboxError("Document sandbox returned invalid plan units")
    return FormatAdapterPlan(
        document_format=DocumentFormat(str(payload["document_format"])),
        adapter_version=str(payload["adapter_version"]),
        units=tuple(_translation_unit_from_json(unit) for unit in units_payload),
        character_count=int(payload["character_count"]),
        estimated_input_tokens=int(payload["estimated_input_tokens"]),
    )


def _translation_unit_from_json(payload: dict[str, Any]) -> FormatTranslationUnit:
    blocks_payload = payload.get("blocks")
    if not isinstance(blocks_payload, list):
        raise DocumentSandboxError("Document sandbox returned invalid unit blocks")
    return FormatTranslationUnit(
        sequence=int(payload["sequence"]),
        blocks=tuple(_text_block_from_json(block) for block in blocks_payload),
        prompt_tier=PromptTier(str(payload["prompt_tier"])),
    )


def _text_block_from_json(payload: dict[str, Any]) -> FormatTextBlock:
    metadata = payload.get("metadata") or []
    return FormatTextBlock(
        index=int(payload["index"]),
        source_block_id=str(payload["source_block_id"]),
        text=str(payload["text"]),
        kind=TextBlockKind(str(payload["kind"])),
        group_id=payload.get("group_id"),
        metadata=tuple((str(key), str(value)) for key, value in metadata),
    )
