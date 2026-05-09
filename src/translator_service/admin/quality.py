from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from translator_service.russian_regression_samples import russian_regression_samples
from translator_service.translation_metrics import score_reference_translation
from translator_service.ukrainian_regression_samples import ukrainian_regression_samples


@dataclass(frozen=True)
class QualitySampleScore:
    sample_id: str
    category: str
    source_language: str
    target_language: str
    meteor: float | None
    chrf: float | None
    status: str
    error: str | None


@dataclass(frozen=True)
class QualityLanguageGroup:
    target_language: str
    label: str
    total_reference_samples: int
    scored_samples: int
    missing_samples: int
    average_meteor: float | None
    average_chrf: float | None
    rows: tuple[QualitySampleScore, ...]


@dataclass(frozen=True)
class QualityRunSummary:
    candidate_path: str
    found: bool
    total_reference_samples: int
    scored_samples: int
    missing_samples: int
    extra_candidates: int
    malformed_candidates: int
    average_meteor: float | None
    average_chrf: float | None
    language_groups: tuple[QualityLanguageGroup, ...]
    rows: tuple[QualitySampleScore, ...]


def build_quality_run_summary(path: str | Path) -> QualityRunSummary:
    candidate_path = Path(path)
    reference_samples = _reference_samples()
    if not candidate_path.exists():
        return _summary(
            candidate_path=candidate_path,
            found=False,
            reference_samples=reference_samples,
            rows=tuple(_missing_row(sample) for sample in reference_samples),
            extra_candidates=0,
            malformed_candidates=0,
        )

    candidates, extra_candidates, malformed_candidates = _read_candidates(
        candidate_path
    )
    rows: list[QualitySampleScore] = []
    for sample in reference_samples:
        candidate = candidates.get(sample.sample_id)
        if candidate is None:
            rows.append(_missing_row(sample))
            continue
        if candidate.error is not None:
            rows.append(
                QualitySampleScore(
                    sample_id=sample.sample_id,
                    category=sample.category,
                    source_language=sample.source_language,
                    target_language=sample.target_language,
                    meteor=None,
                    chrf=None,
                    status="error",
                    error=candidate.error,
                )
            )
            continue
        assert sample.reference_translation is not None
        scores = {
            score.name: score.score
            for score in score_reference_translation(
                candidate=candidate.translated_text or "",
                reference=sample.reference_translation,
            )
        }
        rows.append(
            QualitySampleScore(
                sample_id=sample.sample_id,
                category=sample.category,
                source_language=sample.source_language,
                target_language=sample.target_language,
                meteor=scores["meteor_core"],
                chrf=scores["chrf"],
                status="scored",
                error=None,
            )
        )
    return _summary(
        candidate_path=candidate_path,
        found=True,
        reference_samples=reference_samples,
        rows=tuple(rows),
        extra_candidates=extra_candidates,
        malformed_candidates=malformed_candidates,
    )


@dataclass(frozen=True)
class _Candidate:
    translated_text: str | None
    error: str | None = None


def _read_candidates(path: Path) -> tuple[dict[str, _Candidate], int, int]:
    candidates: dict[str, _Candidate] = {}
    reference_ids = {sample.sample_id for sample in _reference_samples()}
    extra_candidates = 0
    malformed_candidates = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}, 0, 1

    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            malformed_candidates += 1
            continue
        if not isinstance(payload, dict):
            malformed_candidates += 1
            continue
        sample_id = _string(payload.get("sample_id"))
        if sample_id is None:
            malformed_candidates += 1
            continue
        if sample_id not in reference_ids:
            extra_candidates += 1
            continue
        error = _string(payload.get("error"))
        if error is not None:
            candidates[sample_id] = _Candidate(
                translated_text=None,
                error=error,
            )
            continue
        translated_text = payload.get("translated_text")
        if not isinstance(translated_text, str) or not translated_text.strip():
            candidates[sample_id] = _Candidate(
                translated_text=None,
                error="Missing translated_text.",
            )
            continue
        candidates[sample_id] = _Candidate(translated_text=translated_text)
    return candidates, extra_candidates, malformed_candidates


def _summary(
    *,
    candidate_path: Path,
    found: bool,
    reference_samples: tuple[Any, ...],
    rows: tuple[QualitySampleScore, ...],
    extra_candidates: int,
    malformed_candidates: int,
) -> QualityRunSummary:
    scored = tuple(row for row in rows if row.status == "scored")
    missing = tuple(row for row in rows if row.status == "missing")
    return QualityRunSummary(
        candidate_path=str(candidate_path),
        found=found,
        total_reference_samples=len(reference_samples),
        scored_samples=len(scored),
        missing_samples=len(missing),
        extra_candidates=extra_candidates,
        malformed_candidates=malformed_candidates,
        average_meteor=_average(row.meteor for row in scored),
        average_chrf=_average(row.chrf for row in scored),
        language_groups=_language_groups(rows),
        rows=rows,
    )


def _reference_samples() -> tuple[Any, ...]:
    samples = [
        sample
        for sample in (*russian_regression_samples(), *ukrainian_regression_samples())
        if sample.reference_translation is not None
    ]
    samples.sort(
        key=lambda sample: (
            sample.target_language,
            sample.source_language,
            sample.category,
            sample.sample_id,
        )
    )
    return tuple(samples)


def _language_groups(
    rows: tuple[QualitySampleScore, ...],
) -> tuple[QualityLanguageGroup, ...]:
    groups: list[QualityLanguageGroup] = []
    target_languages = sorted({row.target_language for row in rows})
    for target_language in target_languages:
        language_rows = tuple(
            row for row in rows if row.target_language == target_language
        )
        scored = tuple(row for row in language_rows if row.status == "scored")
        missing = tuple(row for row in language_rows if row.status == "missing")
        groups.append(
            QualityLanguageGroup(
                target_language=target_language,
                label=_target_language_label(target_language),
                total_reference_samples=len(language_rows),
                scored_samples=len(scored),
                missing_samples=len(missing),
                average_meteor=_average(row.meteor for row in scored),
                average_chrf=_average(row.chrf for row in scored),
                rows=language_rows,
            )
        )
    return tuple(groups)


def _target_language_label(language: str) -> str:
    labels = {
        "ru": "Russian",
        "uk": "Ukrainian",
    }
    return f"{labels.get(language, language.upper())} ({language})"


def _missing_row(sample: Any) -> QualitySampleScore:
    return QualitySampleScore(
        sample_id=sample.sample_id,
        category=sample.category,
        source_language=sample.source_language,
        target_language=sample.target_language,
        meteor=None,
        chrf=None,
        status="missing",
        error=None,
    )


def _average(values: Any) -> float | None:
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 4)


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
