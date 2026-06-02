from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from re import Pattern


class ModelOutputSafetyReason(StrEnum):
    REFUSAL_OR_SAFETY_MESSAGE = "refusal_or_safety_message"
    PROMPT_OR_ROLE_LEAK = "prompt_or_role_leak"
    TOOL_OR_EXECUTION_CLAIM = "tool_or_execution_claim"
    BOUNDARY_MARKER_LEAK = "boundary_marker_leak"


@dataclass(frozen=True)
class ModelOutputSafetyResult:
    reason: ModelOutputSafetyReason | None = None


def validate_model_output_safety(text: str) -> ModelOutputSafetyResult:
    normalized = _normalize(text)
    if "untrusted_document_content" in normalized:
        return ModelOutputSafetyResult(ModelOutputSafetyReason.BOUNDARY_MARKER_LEAK)
    if _matches_any(normalized, _REFUSAL_PATTERNS):
        return ModelOutputSafetyResult(
            ModelOutputSafetyReason.REFUSAL_OR_SAFETY_MESSAGE
        )
    if _matches_any(normalized, _PROMPT_LEAK_PATTERNS):
        return ModelOutputSafetyResult(ModelOutputSafetyReason.PROMPT_OR_ROLE_LEAK)
    if _matches_any(normalized, _TOOL_EXECUTION_PATTERNS):
        return ModelOutputSafetyResult(ModelOutputSafetyReason.TOOL_OR_EXECUTION_CLAIM)
    return ModelOutputSafetyResult()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _matches_any(text: str, patterns: tuple[Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


_REFUSAL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\bas\s+an\s+ai\s+language\s+model\b.{0,160}"
        r"\b(?:must\s+not|cannot|can't|can\s+not|unable|won't|will\s+not)\b"
        r".{0,120}\b(?:reveal|provide|disclose|comply|follow|execute|run)\b",
        r"\b(i(?:'m| am) sorry|sorry)\b.{0,120}"
        r"\b(?:i\s+)?(?:cannot|can't|can not|unable|won't|will not)\b.{0,120}"
        r"\b(?:execute|run|open|access|comply|follow|perform|fulfill|process|"
        r"system prompt|instruction|request|command|shell|url|link)\b",
        r"\b(?:i\s+)?(?:cannot|can't|can not|unable|won't|will not)\b.{0,120}"
        r"\b(?:comply|assist|help|execute|run|open|reveal|provide)\b.{0,120}"
        r"\b(?:request|instruction|command|system prompt|shell|url|link)\b",
        r"(?:извините|прошу прощения|к сожалению).{0,120}"
        r"(?:не могу|не в состоянии|не буду).{0,120}"
        r"(?:запрос|инструкц|команд|код|оболоч|shell|url|ссылк|системн.{0,30}"
        r"промпт|предыдущ)",
        r"(?:я\s+)?(?:не могу|не в состоянии|не буду).{0,120}"
        r"(?:выполнить|исполнить|запустить|открыть|раскрыть|следовать).{0,120}"
        r"(?:запрос|инструкц|команд|код|оболоч|shell|url|ссылк|системн.{0,30}"
        r"промпт|предыдущ)",
    )
)

_PROMPT_LEAK_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\b(?:system|developer)\s+(?:message|prompt|instructions)\s+"
        r"(?:says|states|is|includes|contains)\b",
        r"\bmy\s+(?:system|developer)\s+(?:message|prompt|instructions)\s+"
        r"(?:say|state|are|include|says|states|is|includes|contains)\b",
        r"(?:системн.{0,30}промпт|системн.{0,30}инструкц).{0,80}"
        r"(?:говорит|содержит|включает|таков|следующ)",
        r"(?:системн.{0,30}сообщен|сообщен.{0,30}разработчик).{0,80}"
        r"(?:говорит|содержит|включает|таков|следующ)",
    )
)

_TOOL_EXECUTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\b(?:i\s+)?(?:executed|ran|opened|accessed)\b.{0,120}"
        r"\b(?:shell|command|url|link|terminal|browser)\b",
        r"\b(?:tool call|function call)\b.{0,120}"
        r"\b(?:completed|executed|ran|opened|accessed|read)\b",
        r"\b(?:i\s+)?(?:opened|accessed|read)\b.{0,80}https?://",
        r"\b(?:i\s+)?(?:opened|accessed)\b.{0,80}"
        r"\b(?:file|path)\b.{0,80}\b(?:/[\w./-]+|[a-z]:\\|file://)\b",
        r"(?:я\s+)?(?:выполнил|исполнил|запустил|открыл).{0,120}"
        r"(?:команд|код|оболоч|shell|url|ссылк|терминал|браузер)",
        r"(?:я\s+)?(?:открыл|открыла|открыло|открыли).{0,80}"
        r"(?:файл|путь).{0,80}(?:/[\w./-]+|[a-z]:\\|file://)",
    )
)
