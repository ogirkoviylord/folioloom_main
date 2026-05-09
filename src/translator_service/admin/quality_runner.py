from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from translator_service.russian_regression_samples import russian_regression_samples


class QualityTranslator(Protocol):
    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        ...


@dataclass(frozen=True)
class QualityRunResult:
    candidate_path: str
    total_samples: int
    translated_samples: int
    failed_samples: int


def write_quality_run(
    path: str | Path,
    *,
    translator: QualityTranslator,
) -> QualityRunResult:
    candidate_path = Path(path)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    samples = tuple(
        sample
        for sample in russian_regression_samples()
        if sample.reference_translation is not None
    )
    translated = 0
    failed = 0
    lines: list[str] = []
    for sample in samples:
        payload: dict[str, str]
        try:
            translated_text = translator.translate(
                text=sample.source_text,
                source_language=sample.source_language,
                target_language=sample.target_language,
            )
        except Exception as error:  # noqa: BLE001 - each sample failure is reported.
            failed += 1
            payload = {
                "sample_id": sample.sample_id,
                "error": _redact_error(error),
            }
        else:
            translated += 1
            payload = {
                "sample_id": sample.sample_id,
                "translated_text": translated_text,
            }
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    candidate_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return QualityRunResult(
        candidate_path=str(candidate_path),
        total_samples=len(samples),
        translated_samples=translated,
        failed_samples=failed,
    )


def _redact_error(error: Exception) -> str:
    message = f"{type(error).__name__}: {error}"
    return re.sub(r"\bsk-[A-Za-z0-9_.-]+", "sk-[redacted]", message)
