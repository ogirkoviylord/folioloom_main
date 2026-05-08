from __future__ import annotations

import base64
import json
import os
import socket
import sys
from typing import Any

from translator_service.documents import DocumentFormat
from translator_service.document_sandbox import SandboxTranslationUnit
from translator_service.extractors import (
    TextExtractionError,
    extract_text_from_docx,
    extract_text_from_epub,
    extract_text_from_txt,
)
from translator_service.format_adapters import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
    plan_docx_translation,
    plan_epub_translation,
    plan_txt_translation,
)
from translator_service.persistent_assembly import (
    assemble_docx_content_from_translated_units,
    assemble_epub_content_from_translated_units,
)


def main() -> int:
    try:
        _disable_network_if_configured()
        request = json.loads(_read_request_bytes().decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("Sandbox request must be an object")
        result = _handle_request(request)
    except Exception as error:
        _write_response(
            {
                "ok": False,
                "error_type": error.__class__.__name__,
                "message": str(error) or "Document sandbox failed",
            }
        )
        return 0

    _write_response({"ok": True, "result": result})
    return 0


def _handle_request(request: dict[str, Any]) -> dict[str, Any]:
    operation = str(request.get("operation", ""))
    document_format = DocumentFormat(str(request["document_format"]))
    content = base64.b64decode(str(request["content_b64"]), validate=True)

    if operation == "extract_text":
        return {"text": _extract_text(document_format=document_format, content=content)}

    if operation == "plan_translation":
        max_fragment_chars = int(request["max_fragment_chars"])
        return _adapter_plan_to_json(
            _plan_translation(
                document_format=document_format,
                content=content,
                max_fragment_chars=max_fragment_chars,
            )
        )

    if operation == "assemble_document":
        translated_units = _translated_units_from_json(
            request.get("translated_units")
        )
        assembled = _assemble_document(
            document_format=document_format,
            content=content,
            translated_units=translated_units,
        )
        return {"content_b64": base64.b64encode(assembled).decode("ascii")}

    raise ValueError(f"Unsupported sandbox operation: {operation}")


def _read_request_bytes() -> bytes:
    max_stdin_bytes = int(os.environ.get("DOCUMENT_SANDBOX_MAX_STDIN_BYTES") or "0")
    if max_stdin_bytes <= 0:
        return sys.stdin.buffer.read()
    payload = sys.stdin.buffer.read(max_stdin_bytes + 1)
    if len(payload) > max_stdin_bytes:
        raise ValueError("Sandbox request is too large")
    return payload


def _disable_network_if_configured() -> None:
    if os.environ.get("DOCUMENT_SANDBOX_DISABLE_NETWORK") != "1":
        return

    def deny_network(*args: Any, **kwargs: Any) -> Any:
        raise OSError("Network is disabled in document sandbox")

    socket.socket = deny_network  # type: ignore[assignment]
    socket.create_connection = deny_network  # type: ignore[assignment]


def _extract_text(*, document_format: DocumentFormat, content: bytes) -> str:
    if document_format is DocumentFormat.TXT:
        return extract_text_from_txt(content)
    if document_format is DocumentFormat.DOCX:
        return extract_text_from_docx(content)
    if document_format is DocumentFormat.EPUB:
        return extract_text_from_epub(content)
    raise TextExtractionError(f"Unsupported document format: {document_format.value}")


def _plan_translation(
    *,
    document_format: DocumentFormat,
    content: bytes,
    max_fragment_chars: int,
) -> FormatAdapterPlan:
    if document_format is DocumentFormat.TXT:
        return plan_txt_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
    if document_format is DocumentFormat.DOCX:
        return plan_docx_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
    if document_format is DocumentFormat.EPUB:
        return plan_epub_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
    raise TextExtractionError(f"Unsupported document format: {document_format.value}")


def _assemble_document(
    *,
    document_format: DocumentFormat,
    content: bytes,
    translated_units: list[SandboxTranslationUnit],
) -> bytes:
    if document_format is DocumentFormat.DOCX:
        return assemble_docx_content_from_translated_units(
            source_content=content,
            translated_units=translated_units,
        )
    if document_format is DocumentFormat.EPUB:
        return assemble_epub_content_from_translated_units(
            source_content=content,
            translated_units=translated_units,
        )
    raise TextExtractionError(
        f"Unsupported document assembly format: {document_format.value}"
    )


def _translated_units_from_json(payload: Any) -> list[SandboxTranslationUnit]:
    if not isinstance(payload, list):
        raise ValueError("translated_units must be a list")
    return [_translated_unit_from_json(unit) for unit in payload]


def _translated_unit_from_json(payload: Any) -> SandboxTranslationUnit:
    if not isinstance(payload, dict):
        raise ValueError("translated unit must be an object")
    source_block_ids = payload.get("source_block_ids")
    if not isinstance(source_block_ids, list):
        raise ValueError("translated unit source_block_ids must be a list")
    return SandboxTranslationUnit(
        source_block_ids=tuple(str(block_id) for block_id in source_block_ids),
        translated_text=str(payload.get("translated_text", "")),
    )


def _adapter_plan_to_json(plan: FormatAdapterPlan) -> dict[str, Any]:
    return {
        "document_format": plan.document_format.value,
        "adapter_version": plan.adapter_version,
        "character_count": plan.character_count,
        "estimated_input_tokens": plan.estimated_input_tokens,
        "units": [_translation_unit_to_json(unit) for unit in plan.units],
    }


def _translation_unit_to_json(unit: FormatTranslationUnit) -> dict[str, Any]:
    return {
        "sequence": unit.sequence,
        "prompt_tier": unit.prompt_tier.value,
        "blocks": [_text_block_to_json(block) for block in unit.blocks],
    }


def _text_block_to_json(block: FormatTextBlock) -> dict[str, Any]:
    return {
        "index": block.index,
        "source_block_id": block.source_block_id,
        "text": block.text,
        "kind": block.kind.value,
        "group_id": block.group_id,
        "metadata": list(block.metadata),
    }


def _write_response(response: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
